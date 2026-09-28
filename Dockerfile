# MinerU — CPU/GPU pipeline backend (slim build)
#
# Image size: ~3 GB  (vs ~30 GB with vllm base + bundled models)
# GPU support: torch + PaddleOCR use GPUs automatically when available
# Models:      downloaded once at first container start into /models (mounted volume)
#              → subsequent starts are instant
#
# Build:
#   docker compose build mineru
#
# Run (via compose):
#   docker compose up -d mineru
#   docker compose exec mineru process_all.sh

FROM python:3.12-slim

# ── System deps: OpenCV + PaddleOCR + CJK/Unicode fonts ──────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev \
        libgomp1 gosu \
        fonts-noto-core fonts-noto-cjk fontconfig \
        wget curl && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ── Install torch pinned to a build that still supports Volta (sm_70) ───────
# The current default 'pip install torch' pulls a CUDA-13 build (torch>=2.12)
# whose kernels are only compiled for sm_75+ — this breaks Tesla V100 GPUs
# (compute capability 7.0) with "CUDA error: no kernel image is available for
# execution on the device". torch/torchvision 2.4.1/0.19.1 (cu121) still
# include sm_70 kernels and are new enough for mineru's 'torch<3' requirement.
RUN pip install --no-cache-dir torch==2.4.1 torchvision==0.19.1 \
        --index-url https://download.pytorch.org/whl/cu121

# ── Install MinerU (core + pipeline backend, no vllm) ────────────────────────
# Installed after torch so pip sees the pinned torch already satisfies
# mineru's 'torch<3' constraint and does not upgrade it.
RUN pip install --no-cache-dir 'mineru[core]' && \
    pip cache purge

# ── Workspace ─────────────────────────────────────────────────────────────────
WORKDIR /workspace
RUN mkdir -p /workspace/input_images /workspace/output_images /models && \
    chmod -R 777 /workspace /models

# ── Batch-processing helper script ───────────────────────────────────────────
COPY process_all.sh /usr/local/bin/process_all.sh
RUN chmod +x /usr/local/bin/process_all.sh

# ── Environment ──────────────────────────────────────────────────────────────
# BACKEND=pipeline: CPU/GPU layout+OCR pipeline (no VLM overhead)
# Models are downloaded to /models (bind-mounted → persists on host)
ENV BACKEND=pipeline \
    MINERU_MODEL_SOURCE=local

# ── Entrypoint: download pipeline models on first run, then idle ──────────────
COPY mineru_entrypoint.sh /usr/local/bin/mineru_entrypoint.sh
RUN chmod +x /usr/local/bin/mineru_entrypoint.sh

ENTRYPOINT ["/usr/local/bin/mineru_entrypoint.sh"]
CMD ["tail", "-f", "/dev/null"]

