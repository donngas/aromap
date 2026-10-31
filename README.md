# Aromap

Interactive indoor scent diffusion simulator for the **Sensation** hackathon theme.
Planned stack: React frontend and FastAPI backend, with approximate relative concentration simulations.

- `frontend/` — frontend project root (npm).
- `backend/` — backend project root (Python, managed with uv).
- `compose.yaml` — runs both services from the repository root.

Only shared scaffolding is included so far. The Dockerfiles are development templates;
application code and dependency manifests are intentionally left to each team lead.

Before running, the frontend needs `package.json`, `package-lock.json`, and a `dev`
script accepting `--host` and `--port`. The backend needs `pyproject.toml`, `uv.lock`,
runtime dependencies including FastAPI and uvicorn, and an `app.main:app` entry point.
Adjust the templates as those projects take shape.

Once both projects are populated:

```sh
docker compose up --build
```

Frontend: http://localhost:5173 · Backend: http://localhost:8000

Optionally set `FRONTEND_PORT` or `BACKEND_PORT` in a root `.env` to change host ports.
The containers use build-time source snapshots; rebuild after code changes.
