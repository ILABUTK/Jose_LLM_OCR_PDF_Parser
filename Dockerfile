# MinerU 3.x (latest) — GPU Docker Image
#
# Base image: vllm/vllm-openai — supports Volta / Turing / Ampere / Ada / Hopper / Blackwell
# (Compute Capability 7.0 – 12.0)
# Requires host NVIDIA driver ≥ CUDA 12.9.1  (check with: nvidia-smi)
#
# Build:
#   docker build -t mineru:latest .
#
# Run (GPU, default hybrid-auto-engine backend):
#   ./docker_run.sh
#
# Run (CPU / pipeline-only, any machine):
#   BACKEND=pipeline ./docker_run.sh

FROM vllm/vllm-openai:v0.11.2

# ── NVIDIA GPU runtime (expose all GPUs, compute + utility caps) ──────────────
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

# ── System dependencies: OpenCV + CJK/Unicode fonts ───────────────────────────
RUN apt-get update && \
    apt-get install -y \
        fonts-noto-core \
        fonts-noto-cjk \
        fontconfig \
        libgl1 && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ── Install latest MinerU (pipeline + VLM + Gradio backends) ──────────────────
RUN python3 -m pip install -U 'mineru[core]' --break-system-packages && \
    python3 -m pip cache purge

# ── Download all models at build time (offline / air-gapped use) ──────────────
RUN mineru-models-download -s huggingface -m all

# ── Workspace ─────────────────────────────────────────────────────────────────
WORKDIR /workspace
RUN mkdir -p /workspace/input_images /workspace/output_images && \
    chmod -R 777 /workspace

# ── Batch-processing helper script ────────────────────────────────────────────
COPY process_all.sh /usr/local/bin/process_all.sh
RUN chmod +x /usr/local/bin/process_all.sh

# ── Entry point: use locally downloaded models, GPU backend by default ─────────
# Default backend: hybrid-auto-engine (GPU VLM acceleration).
# Override with: docker run -e BACKEND=pipeline ... (CPU fallback)
ENV BACKEND=hybrid-auto-engine

ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
CMD ["/bin/bash"]
