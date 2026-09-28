FROM ghcr.io/astral-sh/uv:0.12.13-python3.13-trixie-slim@sha256:c0ba49559fc5622531fd05a5747b52afb49ffa883574bbf8eb719ebd103efb84 AS builder
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

FROM python:3.13-slim-trixie@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b

RUN groupadd --system --gid 999 app \
    && useradd --system --uid 999 --gid 999 --no-create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

USER 999:999
EXPOSE 8000

CMD ["uvicorn", "chapter_and_verse.main:app", "--host", "0.0.0.0", "--port", "8000"]
