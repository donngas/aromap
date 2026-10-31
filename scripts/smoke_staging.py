"""Exercise the staging frontend, proxy, and real recognition provider."""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
FRONTEND = f"http://{HOST}:{os.environ.get('FRONTEND_PORT', '5173')}"
BACKEND = f"http://{HOST}:{os.environ.get('BACKEND_PORT', '8000')}"


def request(url, *, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read()


def main():
    deadline = time.monotonic() + 30
    while True:
        try:
            html = request(FRONTEND + "/")
            break
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
    if b"<html" not in html.lower():
        raise RuntimeError("Frontend did not return HTML")
    if json.loads(request(BACKEND + "/health")) != {"status": "ok"}:
        raise RuntimeError("Backend health check failed")

    image = (ROOT / "backend/tests/floor_plans/recognition/fixtures/cafe_plan.png").read_bytes()
    boundary = "aromap-staging-smoke"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
        f'filename="plan.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
        + image + f"\r\n--{boundary}--\r\n".encode()
    )
    upload = json.loads(request(FRONTEND + "/api/floor-plans/uploads", data=body,
                                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    job = json.loads(request(FRONTEND + "/api/floor-plans/recognitions",
                             data=json.dumps({"image_id": upload["image_id"]}).encode(),
                             headers={"Content-Type": "application/json"}))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status = json.loads(request(FRONTEND + job["status_url"]))
        if status["state"] == "failed":
            raise RuntimeError(f"Recognition failed: {status['error']}")
        if status["state"] == "succeeded":
            layout = status["result"]["floor_plan"]["layout"]
            if layout["width_px"] != upload["width_px"] or not layout["walls"]:
                raise RuntimeError("Recognition returned unexpected geometry")
            print(f"Staging smoke test passed: {len(layout['walls'])} walls detected")
            return
        time.sleep(0.5)
    raise TimeoutError("Recognition did not finish within 90 seconds")


if __name__ == "__main__":
    main()
