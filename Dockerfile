# ============================================================
# Builder
# ============================================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./

# ponytail: package = false, so the project is never installed — one sync builds the whole venv.
# the old second `uv sync` after COPY . . was a no-op whose layer any source edit invalidated.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# ============================================================
# Runtime
# ============================================================
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# ponytail: model weights live on a mounted volume, otherwise every container start re-downloads
# the CrossEncoder, the FastEmbed BM25 model and the docling layout/table models from HuggingFace
ENV HF_HOME=/models/hf \
    TORCH_HOME=/models/torch

# ponytail: CPU inference with two workers on one host — unpinned torch grabs every core and thrashes
ENV OMP_NUM_THREADS=4

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /models/hf /models/torch

WORKDIR /app

# ponytail: the venv only. the old `COPY --from=builder /app /app` re-copied it, since uv built it there.
COPY --from=builder /app/.venv /app/.venv
COPY . /app

# ponytail: PATH already points into the venv, so call python directly.
# `uv run` re-validated the lockfile (and reached for the network) on every container start.
CMD ["python", "-m", "worker.ingestion_worker"]
