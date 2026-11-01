import os
import sqlite3
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


def image_bytes(format="PNG", size=(12, 8), **save_options):
    contents = BytesIO()
    with Image.new("RGB", size, "red") as image:
        image.save(contents, format=format, **save_options)
    return contents.getvalue()


def upload(client, contents=None, filename="floor.png"):
    return client.post("/api/floor-plans/uploads", files={
        "image": (filename, contents if contents is not None else image_bytes(), "application/octet-stream")
    })


def wait_terminal(client, url):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["state"] in {"succeeded", "failed"}:
            return body
        time.sleep(0.02)
    pytest.fail("Recognition did not reach a terminal state")


def test_upload_orientation_retrieval_and_restart(tmp_path):
    settings = Settings(data_dir=tmp_path)
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees clockwise.
    with TestClient(create_app(settings)) as client:
        response = upload(client, image_bytes("JPEG", exif=exif), "../../untrusted.jpg")
        assert response.status_code == 201
        metadata = response.json()
        assert (metadata["width_px"], metadata["height_px"]) == (8, 12)
        assert metadata["media_type"] == "image/png"
        response = client.get(metadata["image_url"])
        assert response.headers["content-type"] == "image/png"
        with Image.open(BytesIO(response.content)) as prepared:
            assert prepared.size == (8, 12)
            assert not prepared.getexif()
        assert not (tmp_path.parent / "untrusted.jpg").exists()
    with TestClient(create_app(settings)) as client:
        assert client.get(metadata["image_url"]).status_code == 200


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_supported_formats(tmp_path, format):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert upload(client, image_bytes(format)).status_code == 201


@pytest.mark.parametrize("contents,status,code", [
    (b"not an image", 422, "invalid_image"),
    (image_bytes("BMP"), 415, "unsupported_image"),
])
def test_invalid_images(tmp_path, contents, status, code):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = upload(client, contents)
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code
        assert not list((tmp_path / "uploads").iterdir())


def test_animated_image_rejected(tmp_path):
    contents = BytesIO()
    with Image.new("RGB", (2, 2), "red") as first, Image.new("RGB", (2, 2), "blue") as second:
        first.save(contents, format="PNG", save_all=True, append_images=[second], duration=100)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = upload(client, contents.getvalue())
        assert response.status_code == 415
        assert response.json()["detail"]["code"] == "animated_image"


def test_byte_pixel_and_request_limits(tmp_path):
    settings = Settings(data_dir=tmp_path, max_upload_bytes=100, max_image_pixels=50)
    with TestClient(create_app(settings)) as client:
        assert upload(client, b"x" * 101).status_code == 413
        assert upload(client, image_bytes(size=(10, 10))).status_code == 413
        # Exceeds the multipart envelope cap, not merely the file-byte check.
        assert upload(client, b"x" * (1024 * 1024 + 1000)).status_code == 413
        assert client.post("/api/floor-plans/uploads").status_code == 422


def test_chunked_upload_limit(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, max_upload_bytes=100))) as client:
        def chunks():
            yield b'--boundary\r\nContent-Disposition: form-data; name="image"; filename="x.png"\r\n\r\n'
            for _ in range(20):
                yield b"x" * 65536
            yield b"\r\n--boundary--\r\n"

        response = client.post("/api/floor-plans/uploads", content=chunks(),
                               headers={"Content-Type": "multipart/form-data; boundary=boundary"})
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "image_too_large"


def test_storage_failure_is_server_error_and_leaves_no_upload(tmp_path, monkeypatch):
    contents = image_bytes()
    with TestClient(create_app(Settings(data_dir=tmp_path)), raise_server_exceptions=False) as client:
        def fail_save(*args, **kwargs):
            raise OSError("Disk is full")

        monkeypatch.setattr(Image.Image, "save", fail_save)
        response = upload(client, contents)
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "internal_error"
        assert not list((tmp_path / "uploads").iterdir())


def test_default_recognition_and_unknown_resources(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        fixture = Path(__file__).parent / "floor_plans/recognition/fixtures/cafe_plan.png"
        metadata = upload(client, fixture.read_bytes()).json()
        response = client.post("/api/floor-plans/recognitions", json={"image_id": metadata["image_id"]})
        assert response.status_code == 202
        result = wait_terminal(client, response.json()["status_url"])
        assert result["state"] == "succeeded"
        layout = result["result"]["floor_plan"]["layout"]
        assert layout["width_px"] == metadata["width_px"]
        assert layout["walls"]
        assert client.get("/api/floor-plans/recognitions/unknown").status_code == 404
        assert client.get("/api/floor-plans/uploads/unknown/image").status_code == 404


def test_invalid_recognizer_fails_startup(tmp_path):
    with pytest.raises((ImportError, AttributeError, ValueError)):
        with TestClient(create_app(Settings(data_dir=tmp_path, recognition_callable="missing_provider:recognize"))):
            pass


@pytest.mark.parametrize("provider,state", [
    ("recognize", "succeeded"), ("recognize_with_domain", "succeeded"), ("fail", "failed"),
])
def test_real_process_job_lifecycle_and_persistence(tmp_path, provider, state):
    settings = Settings(data_dir=tmp_path, recognition_callable=f"tests.recognition_provider:{provider}")
    with TestClient(create_app(settings)) as client:
        metadata = upload(client).json()
        accepted = client.post("/api/floor-plans/recognitions", json={"image_id": metadata["image_id"]})
        assert accepted.status_code == 202
        url = accepted.json()["status_url"]
        result = wait_terminal(client, url)
        assert result["state"] == state
        if state == "succeeded":
            assert result["error"] is None
            assert result["result"]["floor_plan"]["reference_image"] is None
            assert result["result"]["floor_plan"]["layout"]["calibration"] is None
            domain = result["result"]["floor_plan"]["layout"]["indoor_domain"]
            if provider == "recognize_with_domain":
                assert domain["boundary"][2] == {"x": 12, "y": 4}
                assert len(domain["boundary"]) == 6
                assert domain["holes"][0][0] == {"x": 1, "y": 1}
            else:
                assert domain is None
                assert any("Indoor domain estimate is unavailable" in w for w in result["result"]["warnings"])
            warning = result["result"]["warnings"][0]
            assert f"process {os.getpid()};" not in warning
        else:
            assert result["result"] is None
            assert result["error"]["code"] == "recognition_failed"
            assert str(tmp_path) not in result["error"]["message"]
        assert client.post("/api/floor-plans/recognitions", json={"image_id": "unknown"}).status_code == 404
    with TestClient(create_app(settings)) as client:
        assert client.get(url).json() == result


def test_queue_bound_and_active_input_retention(tmp_path):
    settings = Settings(data_dir=tmp_path, queue_capacity=1,
                        recognition_callable="tests.recognition_provider:wait_for_release")
    with TestClient(create_app(settings)) as client:
        metadata = upload(client).json()
        directory = tmp_path / "uploads" / metadata["image_id"]
        payload = {"image_id": metadata["image_id"]}
        first = client.post("/api/floor-plans/recognitions", json=payload).json()
        try:
            deadline = time.monotonic() + 10
            while not (directory / "started").exists():
                assert time.monotonic() < deadline
                time.sleep(0.02)
            second = client.post("/api/floor-plans/recognitions", json=payload)
            assert second.status_code == 202
            assert client.post("/api/floor-plans/recognitions", json=payload).status_code == 429
            with sqlite3.connect(tmp_path / "registry.sqlite3") as db:
                db.execute("UPDATE uploads SET expires_at=0")
                db.execute("UPDATE jobs SET expires_at=0")
            client.app.state.jobs.cleanup()
            assert (directory / "image.png").exists()
            assert client.get(first["status_url"]).status_code == 200
            assert client.get(metadata["image_url"]).status_code == 404
        finally:
            (directory / "release").touch()
        assert wait_terminal(client, first["status_url"])["state"] == "succeeded"
        # The second queued invocation needs its own release signal.
        (directory / "release").touch()
        assert wait_terminal(client, second.json()["status_url"])["state"] == "succeeded"


def test_recognition_timeout_releases_queue(tmp_path):
    settings = Settings(data_dir=tmp_path, recognition_timeout_seconds=3,
                        recognition_callable="tests.recognition_provider:wait_for_release")
    with TestClient(create_app(settings)) as client:
        first_image = upload(client).json()["image_id"]
        second_image = upload(client).json()["image_id"]
        first = client.post("/api/floor-plans/recognitions", json={"image_id": first_image}).json()
        second_dir = tmp_path / "uploads" / second_image
        (second_dir / "release").touch()
        second = client.post("/api/floor-plans/recognitions", json={"image_id": second_image}).json()
        assert wait_terminal(client, first["status_url"])["error"]["code"] == "execution_timeout"
        assert wait_terminal(client, second["status_url"])["state"] == "succeeded"


def test_shutdown_stops_running_recognition(tmp_path):
    settings = Settings(data_dir=tmp_path, recognition_callable="tests.recognition_provider:wait_for_release")
    with TestClient(create_app(settings)) as client:
        image_id = upload(client).json()["image_id"]
        job = client.post("/api/floor-plans/recognitions", json={"image_id": image_id}).json()
        started = tmp_path / "uploads" / image_id / "started"
        deadline = time.monotonic() + 10
        while not started.exists():
            assert time.monotonic() < deadline
            time.sleep(0.02)
    with TestClient(create_app(settings)) as client:
        status = client.get(job["status_url"]).json()
        assert (status["state"], status["error"]["code"]) == ("failed", "job_interrupted")


def test_expiry_cleanup_and_restart_interruption(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        metadata = upload(client).json()
    with sqlite3.connect(tmp_path / "registry.sqlite3") as db:
        now = time.time()
        db.execute("INSERT INTO jobs (id,kind,state,image_id,created_at,updated_at,expires_at) "
                   "VALUES ('interrupted','recognition','running',?,?,?,?)",
                   (metadata["image_id"], now, now, now + 100))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/floor-plans/recognitions/interrupted")
        assert response.json()["state"] == "failed"
        assert response.json()["error"]["code"] == "job_interrupted"
        with sqlite3.connect(tmp_path / "registry.sqlite3") as db:
            db.execute("UPDATE uploads SET expires_at=0")
            db.execute("UPDATE jobs SET expires_at=0")
        client.app.state.jobs.cleanup()
        assert client.get(metadata["image_url"]).status_code == 404
        assert client.get("/api/floor-plans/recognitions/interrupted").status_code == 404
        assert not list((tmp_path / "uploads").iterdir())


def test_cors_and_openapi(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.options("/api/floor-plans/uploads", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"
        })
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        schema = client.get("/openapi.json").json()
        assert "multipart/form-data" in schema["paths"]["/api/floor-plans/uploads"]["post"]["requestBody"]["content"]
        assert "ProjectDocument" not in schema["components"]["schemas"]
        assert "calibration" in schema["components"]["schemas"]["Layout"]["properties"]
        domain_schema = schema["components"]["schemas"]["Layout"]["properties"]["indoor_domain"]
        assert {"$ref": "#/components/schemas/PixelIndoorDomain"} in domain_schema["anyOf"]
        assert {"type": "null"} in domain_schema["anyOf"]
        assert "pixels" in schema["components"]["schemas"]["PixelPoint"]["properties"]["x"]["description"]
        assert "meters" in schema["components"]["schemas"]["MetricPoint"]["properties"]["x"]["description"]


@pytest.mark.parametrize("flag", [None, False, True])
def test_optional_llm_routing(tmp_path, monkeypatch, flag):
    from app.infrastructure import jobs

    selected = []

    class Process:
        exitcode = 0

        def __init__(self, *, target, args):
            selected.append(args[2])
            self.target, self.args = target, args

        def start(self):
            args = list(self.args)
            args[2] = "tests.recognition_provider:recognize"
            self.target(*args)

        def is_alive(self):
            return False

        def close(self):
            pass

    from types import SimpleNamespace

    monkeypatch.setattr(jobs.multiprocessing, "get_context", lambda _: SimpleNamespace(Process=Process))
    settings = Settings(data_dir=tmp_path, recognition_callable="tests.recognition_provider:recognize")
    with TestClient(create_app(settings)) as client:
        image_id = upload(client).json()["image_id"]
        payload = {"image_id": image_id}
        if flag is not None:
            payload["use_llm"] = flag
        response = client.post("/api/floor-plans/recognitions", json=payload)
        assert response.status_code == 202
        assert wait_terminal(client, response.json()["status_url"])["state"] == "succeeded"
        expected = "app.floor_plans.recognition.llm:recognize_floor_plan" if flag else settings.recognition_callable
        assert selected == [expected]
        request = tmp_path / "results" / f"{response.json()['job_id']}.request.json"
        import json
        assert json.loads(request.read_text()) == {"use_llm": bool(flag)}
        assert client.post("/api/floor-plans/recognitions", json={"image_id": image_id, "use_llm": "yes"}).status_code == 422


def test_llm_without_credentials_fails_job_and_default_still_works(tmp_path, monkeypatch):
    # Empty inherited environment wins over any developer .env in the spawned child.
    monkeypatch.setenv("OPENAI_API_KEY", "")
    settings = Settings(data_dir=tmp_path, recognition_callable="tests.recognition_provider:recognize")
    with TestClient(create_app(settings)) as client:
        image_id = upload(client).json()["image_id"]
        accepted = client.post("/api/floor-plans/recognitions", json={"image_id": image_id, "use_llm": True})
        result = wait_terminal(client, accepted.json()["status_url"])
        assert result["state"] == "failed"
        assert result["error"]["code"] == "recognition_failed"
        assert result["result"] is None
        accepted = client.post("/api/floor-plans/recognitions", json={"image_id": image_id})
        assert wait_terminal(client, accepted.json()["status_url"])["state"] == "succeeded"
