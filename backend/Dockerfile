# Single-host backend; mount AROMAP_DATA_DIR for persistent temporary resources.
FROM python:3.12-slim AS base

# Use PyPI rather than a second container registry for the uv binary.
RUN pip install --no-cache-dir uv==0.12.19

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./

FROM base AS development
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app/app"]

FROM base AS production
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
