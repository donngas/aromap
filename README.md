# Aromap

Interactive indoor scent diffusion simulator for the **Sensation** hackathon theme.
Planned stack: React frontend and FastAPI backend, with approximate relative concentration simulations.

- `frontend/` — frontend project root (npm).
- `backend/` — backend project root (Python, managed with uv).
- `compose.yaml` — runs both services from the repository root.

The backend provides image uploads and recognition job infrastructure. See
[backend/README.md](backend/README.md) for setup, API contracts, and current scope.

Before running, the frontend needs `package.json`, `package-lock.json`, and a `dev`
script accepting `--host` and `--port`. To run only the backend now, use
`docker compose up --build backend`.

Once both projects are populated:

```sh
docker compose up --build
```

Frontend: http://localhost:5173 · Backend: http://localhost:8000

Optionally set `FRONTEND_PORT` or `BACKEND_PORT` in a root `.env` to change host ports.
The containers use build-time source snapshots; rebuild after code changes.
