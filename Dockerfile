FROM ghcr.io/astral-sh/uv:0.13.6-python3.13-trixie-slim@sha256:e586c1c65b7071aec78f02c5587c76c5011159cd76b3d6f1255f40e48e850abc AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Dependencies first, from the lock file only. Cached until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Installed as a normal package, so the final stage needs only .venv.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

RUN groupadd --system --gid 999 app \
    && useradd --system --uid 999 --gid 999 --no-create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# `alembic upgrade head` runs from /app, where it finds alembic.ini.
COPY alembic.ini ./
COPY migrations ./migrations

USER 999:999
EXPOSE 8000

CMD ["uvicorn", "chapter_and_verse.main:app", "--host", "0.0.0.0", "--port", "8000"]
