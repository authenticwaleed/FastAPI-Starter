# syntax=docker/dockerfile:1

# Kept at the Python version the project develops against, so a problem that
# only appears on one of them cannot hide until deployment.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1


FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve in their own layer, from the lock file alone, so
# editing application code does not re-download the world on every build.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM base AS runtime

# An unprivileged user, so a process that gets away from us cannot write to
# the image or read files it was never given.
RUN useradd --create-home --uid 1000 app

WORKDIR /app

COPY --from=builder --chown=app:app /app /app

# Put the virtualenv first so `uvicorn` and `alembic` resolve without uv.
ENV PATH="/app/.venv/bin:$PATH"

USER app

EXPOSE 8000

# No configuration is baked in: DATABASE_URL, JWT_SECRET_KEY and the rest
# arrive from the environment, and .dockerignore keeps .env out of here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
