"""Single-process API dispatcher with a bounded queue and one child process.

SQLite records survive restarts; the queue does not. Unfinished jobs fail on
startup. No database transaction is held during recognition.
"""

import asyncio
import importlib
import logging
import json
from datetime import datetime, timezone
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from uuid import uuid4

from fastapi import HTTPException

from app.config import Settings
from app.errors import api_error
from app.floor_plans.models import RecognitionDraft
from app.infrastructure.database import Database
from app.infrastructure.storage import LocalStorage
from app.simulations.execution import execute_simulation
from app.simulations.limits import ExecutionLimits

logger = logging.getLogger(__name__)
TERMINATION_GRACE_S = 2.0


async def stop_process(process):
    """Terminate a child, escalating to kill without blocking the event loop."""
    if process.is_alive():
        process.terminate()
        await asyncio.to_thread(process.join, TERMINATION_GRACE_S)
    if process.is_alive():
        process.kill()
        await asyncio.to_thread(process.join, TERMINATION_GRACE_S)
    if process.is_alive():
        logger.error("Simulation process %s did not exit after kill", process.pid)
    else:
        process.close()


def load_recognizer(target: str):
    module, name = target.split(":", 1)
    function = getattr(importlib.import_module(module), name)
    if not callable(function):
        raise ValueError("Recognition provider must be callable")
    return function


def execute_recognition(target: str, image_path: str, width: int, height: int) -> dict:
    """Child-process boundary; validate the basic handoff before publishing."""
    from pathlib import Path

    draft = RecognitionDraft.model_validate(load_recognizer(target)(Path(image_path)))
    layout = draft.floor_plan.layout
    if (layout.width_px, layout.height_px) != (width, height):
        raise ValueError("Recognition dimensions must match the prepared image")
    if layout.revision != 1 or layout.calibration is not None or draft.floor_plan.reference_image is not None:
        raise ValueError("Recognition output violates the draft handoff contract")
    if layout.indoor_domain is None:
        warning = "Indoor domain estimate is unavailable; trace the indoor boundary manually."
        if warning not in draft.warnings:
            draft.warnings.append(warning)
    return draft.model_dump(mode="json")


class Jobs:
    def __init__(self, settings: Settings, database: Database, storage: LocalStorage):
        self.settings = settings
        self.database = database
        self.storage = storage
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.queue_capacity)
        self.executor: ProcessPoolExecutor | None = None
        self.worker: asyncio.Task | None = None
        self.cleaner: asyncio.Task | None = None

    async def start(self):
        with self.database.connect() as db:
            db.execute(
                "UPDATE jobs SET state='failed', updated_at=?, error_code='job_interrupted', "
                "error_message='Processing was interrupted by a backend restart.' "
                "WHERE state IN ('queued', 'running')", (time.time(),)
            )
        try:
            self.cleanup()
        except OSError:
            logger.exception("Artifact cleanup failed at startup; retrying next interval")
        if self.settings.recognition_callable:
            load_recognizer(self.settings.recognition_callable)
            self.executor = ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn")
            )
        self.worker = asyncio.create_task(self.dispatch(), name="job-worker")
        self.cleaner = asyncio.create_task(self.periodic_cleanup(), name="artifact-cleanup")

    async def close(self):
        for task in (self.cleaner, self.worker):
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in (self.cleaner, self.worker) if t), return_exceptions=True)
        if self.executor:
            await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=True)
        with self.database.connect() as db:
            db.execute(
                "UPDATE jobs SET state='failed', updated_at=?, error_code='job_interrupted', "
                "error_message='Processing was interrupted by backend shutdown.' "
                "WHERE state IN ('queued', 'running')", (time.time(),)
            )

    def submit_recognition(self, image_id: str) -> str:
        if not self.settings.recognition_callable:
            raise api_error(503, "recognition_unavailable", "Recognition is not integrated yet.")
        if self.queue.full():
            raise api_error(429, "queue_full", "Recognition queue is full; try again later.")
        now = time.time()
        job_id = uuid4().hex
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            image = db.execute(
                "SELECT * FROM uploads WHERE id=? AND expires_at>?", (image_id, now)
            ).fetchone()
            if image is None or not self.storage.path(image["relative_path"]).is_file():
                raise api_error(404, "image_not_found", "Image is unknown or expired.")
            db.execute(
                "INSERT INTO jobs (id, kind, state, image_id, created_at, updated_at, expires_at) "
                "VALUES (?, 'recognition', 'queued', ?, ?, ?, ?)",
                (job_id, image_id, now, now, now + self.settings.retention_seconds),
            )
        # Event-loop only: no await between the capacity check and enqueue.
        self.queue.put_nowait(job_id)
        return job_id

    def submit_simulation(self, payload) -> str:
        if self.queue.full():
            raise api_error(429, "queue_full", "Job queue is full; try again later.")
        now = time.time()
        job_id = uuid4().hex
        path = f"results/{job_id}.request.json"
        self.storage.write_json(path, payload.model_dump(mode="json"))
        try:
            with self.database.connect() as db:
                db.execute("INSERT INTO jobs (id, kind, state, created_at, updated_at, expires_at) "
                           "VALUES (?, 'simulation', 'queued', ?, ?, ?)",
                           (job_id, now, now, now + self.settings.retention_seconds))
            self.queue.put_nowait(job_id)
        except Exception:
            self.storage.remove(path)
            raise
        return job_id

    def simulation_status(self, job_id: str):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND kind='simulation' "
                             "AND (expires_at>? OR state IN ('queued', 'running'))", (job_id, time.time())).fetchone()
        if row is None:
            raise api_error(404, "job_not_found", "Simulation job is unknown or expired.")
        try:
            request = json.loads(self.storage.path(f"results/{job_id}.request.json").read_text())
            result = json.loads(self.storage.path(row["result_path"]).read_text())["result"] if row["state"] == "succeeded" else None
        except (OSError, ValueError, KeyError, TypeError):
            raise api_error(500, "result_unavailable", "The simulation result is unavailable.")
        return {"job_id": job_id, "client_request_id": request["client_request_id"], "state": row["state"],
                "created_at": row["created_at"], "updated_at": row["updated_at"], "expires_at": row["expires_at"],
                "result": result, "error": {"code": row["error_code"], "message": row["error_message"]} if row["state"] == "failed" else None}

    def simulation_fields(self, job_id: str):
        try:
            status = self.simulation_status(job_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise api_error(404, "result_not_found", "Simulation fields are unknown or expired.") from exc
            raise
        path = self.storage.path(f"results/{job_id}.npz")
        if status["state"] != "succeeded" or not path.is_file():
            raise api_error(404, "result_not_found", "Simulation fields are unknown or expired.")
        return path

    async def run_simulation(self, job_id: str):
        expires = time.time() + self.settings.retention_seconds
        process = multiprocessing.get_context("spawn").Process(target=execute_simulation, args=(str(self.storage.root), job_id, expires))
        process.start()
        try:
            deadline = asyncio.get_running_loop().time() + ExecutionLimits().max_runtime_s
            while process.is_alive():
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("Simulation exceeded its execution deadline")
                await asyncio.sleep(min(0.1, remaining))
            path = f"results/{job_id}.json"
            if process.exitcode != 0:
                raise RuntimeError("Simulation process exited unexpectedly")
            outcome = json.loads(self.storage.path(path).read_text())
            now = time.time()
            expires = now + self.settings.retention_seconds
            if "result" in outcome:
                outcome["result"]["expires_at"] = datetime.fromtimestamp(expires, timezone.utc).isoformat()
                self.storage.write_json(path, outcome)
            with self.database.connect() as db:
                if "error" in outcome:
                    db.execute("UPDATE jobs SET state='failed', updated_at=?, expires_at=?, error_code=?, error_message=? WHERE id=?",
                               (now, expires, outcome["error"]["code"], outcome["error"]["message"], job_id))
                else:
                    db.execute("UPDATE jobs SET state='succeeded', updated_at=?, expires_at=?, result_path=? WHERE id=?",
                               (now, expires, path, job_id))
        finally:
            await stop_process(process)

    def recognition_status(self, job_id: str):
        with self.database.connect() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND kind='recognition' "
                "AND (expires_at>? OR state IN ('queued', 'running'))", (job_id, time.time())
            ).fetchone()
        if row is None:
            raise api_error(404, "job_not_found", "Job is unknown or expired.")
        result = None
        if row["state"] == "succeeded":
            try:
                result = RecognitionDraft.model_validate_json(
                    self.storage.path(row["result_path"]).read_text(encoding="utf-8")
                )
                # Keep the shared model intact; calibration is browser-owned.
                result.floor_plan.layout.calibration = None
            except (OSError, ValueError):
                raise api_error(500, "result_unavailable", "The recognition result is unavailable.")
        return {
            "job_id": row["id"], "state": row["state"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "expires_at": row["expires_at"], "result": result,
            "error": {"code": row["error_code"], "message": row["error_message"]}
            if row["state"] == "failed" else None,
        }

    async def dispatch(self):
        while True:
            job_id = await self.queue.get()
            kind = None
            try:
                with self.database.connect() as db:
                    kind = db.execute("SELECT kind FROM jobs WHERE id=?", (job_id,)).fetchone()["kind"]
                    image = db.execute(
                        "SELECT u.* FROM uploads u JOIN jobs j ON j.image_id=u.id WHERE j.id=?",
                        (job_id,),
                    ).fetchone()
                    db.execute("UPDATE jobs SET state='running', updated_at=? WHERE id=?",
                               (time.time(), job_id))
                if kind == "simulation":
                    await self.run_simulation(job_id)
                    continue
                result = await asyncio.get_running_loop().run_in_executor(
                    self.executor, execute_recognition, self.settings.recognition_callable,
                    str(self.storage.path(image["relative_path"])), image["width_px"], image["height_px"],
                )
                relative_path = f"results/{job_id}.json"
                self.storage.write_json(relative_path, result)
                now = time.time()
                with self.database.connect() as db:
                    db.execute(
                        "UPDATE jobs SET state='succeeded', updated_at=?, expires_at=?, result_path=? WHERE id=?",
                        (now, now + self.settings.retention_seconds, relative_path, job_id),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Job %s failed", job_id)
                now = time.time()
                try:
                    with self.database.connect() as db:
                        code = ("execution_timeout" if isinstance(exc, TimeoutError) else
                                "recognition_failed" if kind == "recognition" else
                                "simulation_failed" if kind == "simulation" else "job_failed")
                        db.execute(
                            "UPDATE jobs SET state='failed', updated_at=?, expires_at=?, "
                            "error_code=?, error_message=? WHERE id=?",
                            (now, now + self.settings.retention_seconds, code, "Job could not complete.", job_id),
                        )
                except Exception:
                    logger.exception("Could not record failure for job %s", job_id)
            finally:
                self.queue.task_done()

    def cleanup(self):
        now = time.time()
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            expired_jobs = db.execute(
                "SELECT id, result_path FROM jobs WHERE expires_at<=? AND state IN ('succeeded', 'failed')",
                (now,),
            ).fetchall()
            for row in expired_jobs:
                try:
                    if row["result_path"]:
                        self.storage.remove(row["result_path"])
                    for suffix in (".request.json", ".npz", ".npz.tmp", ".json"):
                        self.storage.remove(f"results/{row['id']}{suffix}")
                except OSError:
                    logger.exception("Could not clean job %s; retrying later", row["id"])
                    continue
                db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
            # Keep image records/files while any unexpired/active job references them.
            expired_uploads = db.execute(
                "SELECT id, relative_path FROM uploads u WHERE expires_at<=? "
                "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.image_id=u.id)", (now,)
            ).fetchall()
            for row in expired_uploads:
                try:
                    self.storage.remove(row["relative_path"])
                except OSError:
                    logger.exception("Could not clean upload %s; retrying later", row["id"])
                    continue
                db.execute("DELETE FROM uploads WHERE id=?", (row["id"],))
            referenced = {row["relative_path"] for row in db.execute("SELECT relative_path FROM uploads")}
            for row in db.execute("SELECT id, result_path FROM jobs"):
                # Protect results between file publication and the success update.
                for suffix in (".json", ".request.json", ".npz", ".npz.tmp"):
                    referenced.add(f"results/{row['id']}{suffix}")
                if row["result_path"]:
                    referenced.add(row["result_path"])
            self.storage.prune_orphans(referenced, now - self.settings.retention_seconds)

    async def periodic_cleanup(self):
        while True:
            await asyncio.sleep(self.settings.cleanup_interval_seconds)
            try:
                self.cleanup()
            except Exception:
                logger.exception("Artifact cleanup failed; retrying next interval")
