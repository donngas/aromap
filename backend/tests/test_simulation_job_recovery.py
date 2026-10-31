"""Simulation worker timeout and dispatcher recovery."""
import asyncio
import multiprocessing
import signal
import time
from contextlib import contextmanager

from app.config import Settings
from app.infrastructure.database import Database
from app.infrastructure.jobs import Jobs, stop_process
from app.infrastructure.storage import LocalStorage


def ignore_termination(ready):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    ready.set()
    while True:
        time.sleep(1)


def test_stubborn_process_is_killed(monkeypatch):
    monkeypatch.setattr("app.infrastructure.jobs.TERMINATION_GRACE_S", 0.1)
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    process = ctx.Process(target=ignore_termination, args=(ready,))
    process.start()
    try:
        assert ready.wait(10)
        started = time.monotonic()
        asyncio.run(stop_process(process))
        assert time.monotonic() - started < 5
        assert process._closed
    finally:
        if not process._closed:
            process.kill()
            process.join()
            process.close()


def test_dispatcher_survives_initial_lookup_failure(tmp_path, monkeypatch):
    storage = LocalStorage(tmp_path)
    database = Database(tmp_path / "registry.sqlite3")
    database.initialize()
    jobs = Jobs(Settings(data_dir=tmp_path), database, storage)
    now = time.time()
    with database.connect() as db:
        for job_id in ("first", "second"):
            db.execute("INSERT INTO jobs (id,kind,state,created_at,updated_at,expires_at) "
                       "VALUES (?, 'simulation', 'queued', ?, ?, ?)",
                       (job_id, now, now, now + 100))
    real_connect = database.connect
    fail_once = True

    @contextmanager
    def flaky_connect():
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("temporary database failure")
        with real_connect() as db:
            yield db

    processed = []

    async def fake_simulation(job_id):
        processed.append(job_id)

    monkeypatch.setattr(database, "connect", flaky_connect)
    monkeypatch.setattr(jobs, "run_simulation", fake_simulation)

    async def exercise():
        jobs.queue.put_nowait("first")
        jobs.queue.put_nowait("second")
        worker = asyncio.create_task(jobs.dispatch())
        await asyncio.wait_for(jobs.queue.join(), timeout=3)
        assert not worker.done()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(exercise())
    with real_connect() as db:
        first = db.execute("SELECT state, error_code FROM jobs WHERE id='first'").fetchone()
    assert (first["state"], first["error_code"]) == ("failed", "job_failed")
    assert processed == ["second"]
