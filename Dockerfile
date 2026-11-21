FROM ghcr.io/astral-sh/uv:0.13.8-python3.13-trixie-slim@sha256:9a9f205ad2f9aaf63597afef4042c455392f9253937028264b98226e91c09518 AS builder
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

# The embedding model goes into the image, so a pod starts without the network.
ENV FASTEMBED_CACHE_PATH=/app/models
RUN /app/.venv/bin/python -c "from chapter_and_verse.embeddings import FastEmbedder; FastEmbedder()" \
    && chmod -R a+rX /app/models

FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

RUN groupadd --system --gid 999 app \
    && useradd --system --uid 999 --gid 999 --no-create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/models /app/models
# Read the model from the image, never ask Hugging Face for a newer one, and send no
# usage data from onnxruntime, which runs the model.
ENV PATH="/app/.venv/bin:$PATH" \
    FASTEMBED_CACHE_PATH=/app/models \
    HF_HUB_OFFLINE=1 \
    ORT_DISABLE_TELEMETRY=1

# `alembic upgrade head` runs from /app, where it finds alembic.ini.
COPY alembic.ini ./
COPY migrations ./migrations

USER 999:999
EXPOSE 8000

CMD ["uvicorn", "chapter_and_verse.main:app", "--host", "0.0.0.0", "--port", "8000"]
