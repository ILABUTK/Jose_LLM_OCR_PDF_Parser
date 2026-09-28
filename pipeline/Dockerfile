FROM python:3.11-slim

# ── Python dependencies ───────────────────────────────────────────────────────
COPY paper_generation/requirements.txt /tmp/paper_req.txt
RUN pip install --no-cache-dir -r /tmp/paper_req.txt

# All code is injected at runtime via the mounted volume at /workspace
WORKDIR /workspace

# Idle — the UI triggers runs via: docker exec -w /workspace/paper_generation jose-pipeline python <script>
# LaTeX (pdflatex/bibtex) is compiled on the host; see ui/app.py latex_compile()
CMD ["tail", "-f", "/dev/null"]
