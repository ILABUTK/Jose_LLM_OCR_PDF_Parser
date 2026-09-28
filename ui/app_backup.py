"""Streamlit UI — Jose LLM-OCR PDF Parser pipeline.

Pages (sidebar):
  📊 Status      — pipeline checklist + OCR progress bar
  📁 PDFs        — table of all PDFs with OCR status
  🔍 OCR         — trigger MinerU, stream live output
  🧬 Ontologies  — run stage 01, edit + save JSON ontologies
  ⚙️ Generate    — run stages 02-07, stream output, download PDF
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LLM-OCR Pipeline",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Bootstrap-inspired CSS ────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background: #1e293b !important; }
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div { color: #e2e8f0 !important; }

.metric-card {
    background: #fff; border: 1px solid #dee2e6; border-radius: 8px;
    padding: 18px 20px; text-align: center;
    box-shadow: 0 1px 4px rgba(0,0,0,.07); margin-bottom: 8px;
}
.metric-val { font-size: 2rem; font-weight: 700; color: #007934; line-height: 1.2; }
.metric-lbl { font-size: .80rem; color: #6c757d; margin-top: 4px; }

.badge-done    { background:#d1fae5; color:#065f46; padding:2px 10px;
                 border-radius:12px; font-size:.78rem; font-weight:600; display:inline-block; }
.badge-pending { background:#f1f5f9; color:#64748b; padding:2px 10px;
                 border-radius:12px; font-size:.78rem; display:inline-block; }

.pipe-table { width:100%; border-collapse:collapse; font-size:.88rem; margin-top:8px; }
.pipe-table th { background:#007934; color:#fff; padding:9px 12px; text-align:left; }
.pipe-table td { padding:8px 12px; border-bottom:1px solid #f1f5f9; }
.pipe-table tr:hover td { background:#f8fafc; }
</style>
""", unsafe_allow_html=True)

# ── Paths (inside container — workspace mounted from host) ────────────────────
WORKSPACE    = Path("/workspace")
PDF_DIR      = WORKSPACE / "mineru" / "PDFs" / "files"
OCR_OUT      = WORKSPACE / "mineru" / "output_images"
PIPELINE     = WORKSPACE / "paper_generation"
ONTO_DIR     = PIPELINE / "ontologies"
OUTPUT_DIR   = PIPELINE / "output"
STRUCT_JSON  = ONTO_DIR / "structure_ontology.json"
STYLE_JSON   = ONTO_DIR / "style_ontology.json"
FINAL_PDF    = OUTPUT_DIR / "paper.pdf"
BIB_FILE     = WORKSPACE / "mineru" / "PDFs" / "PDFs.bib"

MINERU_CTR   = os.environ.get("MINERU_CONTAINER",   "mineru")
PIPE_CTR     = os.environ.get("PIPELINE_CONTAINER", "llm-pipeline")

# ── Command builders ──────────────────────────────────────────────────────────
def _exec(script: str) -> list[str]:
    return ["docker", "exec", "-i", "-w", "/workspace/paper_generation",
            PIPE_CTR, "python", "-u", script]

def _latex_cmd(*cmd: str) -> list[str]:
    return ["docker", "exec", "-i", "-w", "/workspace/paper_generation/output",
            PIPE_CTR, *cmd]

# ── Streaming runner ──────────────────────────────────────────────────────────
def _run_stream(cmd: list[str]) -> int:
    """Run cmd, stream output into a st.code block. Returns exit code."""
    box = st.empty()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert proc.stdout
    log = "$ " + " ".join(cmd) + "\n"
    for line in proc.stdout:
        log += line
        box.code(log[-8000:], language="bash")
    proc.wait()
    log += f"\n[exit {proc.returncode}]"
    box.code(log[-8000:], language="bash")
    return proc.returncode

# ── Status helper ─────────────────────────────────────────────────────────────
def get_status() -> dict:
    n_pdfs = sum(1 for p in PDF_DIR.iterdir() if p.is_dir()) if PDF_DIR.exists() else 0
    n_ocr  = sum(1 for p in OCR_OUT.iterdir() if p.is_dir()) if OCR_OUT.exists() else 0
    return {
        "n_pdfs":  n_pdfs,
        "n_ocr":   n_ocr,
        "bib":     BIB_FILE.exists(),
        "struct":  STRUCT_JSON.exists(),
        "style":   STYLE_JSON.exists(),
        "outline": (OUTPUT_DIR / "outline.json").exists(),
        "draft":   (OUTPUT_DIR / "draft_sections.json").exists(),
        "tex":     (OUTPUT_DIR / "paper.tex").exists(),
        "pdf":     FINAL_PDF.exists(),
    }

# ── Sidebar ───────────────────────────────────────────────────────────────────
PAGES = ["📊 Status", "� Import", "�📁 PDFs", "🔍 OCR", "🧬 Ontologies", "⚙️ Generate"]

with st.sidebar:
    st.markdown("### 🧪 LLM-OCR\nPDF Pipeline")
    st.markdown("---")
    page = st.radio("nav", PAGES, label_visibility="collapsed")
    st.markdown("---")
    s = get_status()
    pct = s["n_ocr"] / max(s["n_pdfs"], 1)
    st.markdown(f"**OCR Progress:** {s['n_ocr']}/{s['n_pdfs']}")
    st.progress(pct)
    if s["pdf"]:
        st.success("📄 Paper PDF ready")
    elif s["tex"]:
        st.info("📝 LaTeX ready — compile")
    elif s["draft"]:
        st.info("✍️ Draft written")
    elif s["struct"]:
        st.info("🧬 Ontologies ready")
    elif s["n_ocr"] > 0:
        st.warning("🔍 OCR in progress")
    else:
        st.warning("▶ Start with OCR tab")

# ═════════════════════════════════════════════════════════════════════════════
# STATUS
# ═════════════════════════════════════════════════════════════════════════════
if page == PAGES[0]:
    col_h, col_btn = st.columns([5, 1])
    with col_h:
        st.title("📊 Pipeline Status")
    with col_btn:
        st.write("")
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

    s = get_status()
    c1, c2, c3, c4 = st.columns(4)
    for col, val, lbl in [
        (c1, s["n_pdfs"],                    "Total PDFs"),
        (c2, f"{s['n_ocr']}/{s['n_pdfs']}",  "OCR Done"),
        (c3, "✅" if s["bib"] else "⬜",      "PDFs.bib"),
        (c4, "✅" if s["pdf"] else "⬜",      "Final PDF"),
    ]:
        col.markdown(
            f'<div class="metric-card"><div class="metric-val">{val}</div>'
            f'<div class="metric-lbl">{lbl}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    pct = s["n_ocr"] / max(s["n_pdfs"], 1)
    st.progress(pct, text=f"OCR: {s['n_ocr']}/{s['n_pdfs']} papers ({pct*100:.0f}%)")
    st.markdown("---")

    steps = [
        ("1", "PDFs imported",        s["n_pdfs"] > 0,
              f"{s['n_pdfs']} sub-folders in mineru/PDFs/files/"),
        ("2", "PDFs.bib present",     s["bib"],
              "mineru/PDFs/PDFs.bib"),
        ("3", "OCR complete",         s["n_ocr"] >= s["n_pdfs"] and s["n_pdfs"] > 0,
              f"{s['n_ocr']}/{s['n_pdfs']} papers parsed by MinerU"),
        ("4", "Structure ontology",   s["struct"],
              "paper_generation/ontologies/structure_ontology.json"),
        ("5", "Style ontology",       s["style"],
              "paper_generation/ontologies/style_ontology.json"),
        ("6", "Outline (stage 02)",   s["outline"],
              "paper_generation/output/outline.json"),
        ("7", "Draft (stage 03)",     s["draft"],
              "paper_generation/output/draft_sections.json"),
        ("8", "paper.tex (stage 05)", s["tex"],
              "paper_generation/output/paper.tex"),
        ("9", "paper.pdf",            s["pdf"],
              "paper_generation/output/paper.pdf"),
    ]
    rows = "".join(
        f'<tr><td style="color:#94a3b8;font-size:.8rem;text-align:center">{n}</td>'
        f'<td style="font-weight:500">{label}</td>'
        f'<td><span class="{"badge-done" if done else "badge-pending"}">'
        f'{"✅ Done" if done else "⬜ Pending"}</span></td>'
        f'<td style="color:#94a3b8;font-size:.83rem">{detail}</td></tr>'
        for n, label, done, detail in steps
    )
    st.markdown(
        f'<table class="pipe-table"><thead><tr>'
        f'<th>#</th><th>Step</th><th>Status</th><th>Detail</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>',
        unsafe_allow_html=True,
    )

# ═════════════════════════════════════════════════════════════════════════════
# IMPORT  (drag-and-drop PDFs + .bib)
# ═════════════════════════════════════════════════════════════════════════════
elif page == PAGES[1]:
    st.title("📤 Import Papers")
    st.markdown(
        "Drop your **Zotero `.bib` export** and your **PDF files** here.  \n"
        "The `.bib` goes to `mineru/PDFs/PDFs.bib` and each PDF is placed in "
        "`mineru/PDFs/files/<ref#>/` (ref# = order of upload or citekey).  \n"
        "After upload, go to **🔍 OCR** to process them."
    )

    st.markdown("---")

    # ── BIB upload ────────────────────────────────────────────────────────────
    st.subheader("1 · Upload .bib file (Zotero export)")
    bib_up = st.file_uploader(
        "Drag your exported `.bib` file here",
        type=["bib"],
        key="bib_uploader",
    )
    if bib_up is not None:
        dest_bib = WORKSPACE / "mineru" / "PDFs" / "PDFs.bib"
        dest_bib.parent.mkdir(parents=True, exist_ok=True)
        dest_bib.write_bytes(bib_up.getbuffer())
        st.success(f"✅ Saved `PDFs.bib` ({len(bib_up.getvalue())//1024} KB) — "
                   f"{bib_up.name}")
        # Count entries
        n_entries = bib_up.getvalue().decode("utf-8", errors="ignore").count("@")
        st.info(f"~{n_entries} bib entries detected.")

    if BIB_FILE.exists():
        n_bib = BIB_FILE.read_text(errors="ignore").count("@")
        st.caption(f"Current `PDFs.bib`: **{n_bib} entries** — "
                   f"{BIB_FILE.stat().st_size//1024} KB")

    st.markdown("---")

    # ── PDF upload ────────────────────────────────────────────────────────────
    st.subheader("2 · Upload PDFs")
    st.caption(
        "Each PDF will be saved as `mineru/PDFs/files/<slug>/<filename>.pdf`.  \n"
        "The slug is the filename stem (spaces → underscores, max 40 chars) — "
        "matches Zotero's citekey naming when you export PDFs alongside the `.bib`."
    )

    pdf_ups = st.file_uploader(
        "Drag one or more PDF files here",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_uploader",
    )

    if pdf_ups:
        dest_root = WORKSPACE / "mineru" / "PDFs" / "files"
        dest_root.mkdir(parents=True, exist_ok=True)
        saved, skipped = [], []
        for uf in pdf_ups:
            slug = uf.name.replace(" ", "_")[:40].rstrip("_")
            slug = "".join(c for c in slug if c.isalnum() or c in "_-.") or "paper"
            slug = Path(slug).stem          # strip .pdf from slug
            folder = dest_root / slug
            folder.mkdir(exist_ok=True)
            dest_pdf = folder / uf.name
            if dest_pdf.exists():
                skipped.append(uf.name)
            else:
                dest_pdf.write_bytes(uf.getbuffer())
                saved.append((slug, uf.name, len(uf.getvalue())))

        if saved:
            st.success(f"✅ Saved {len(saved)} PDF(s):")
            for slug, fname, sz in saved:
                st.markdown(f"- `files/{slug}/{fname}` ({sz//1024} KB)")
        if skipped:
            st.warning(f"Already existed (skipped): {', '.join(skipped)}")

    # ── Summary ───────────────────────────────────────────────────────────────
    st.markdown("---")
    n_pdfs = sum(1 for p in PDF_DIR.iterdir() if p.is_dir()) if PDF_DIR.exists() else 0
    n_ocr  = sum(1 for p in OCR_OUT.iterdir() if p.is_dir()) if OCR_OUT.exists() else 0
    c1, c2 = st.columns(2)
    c1.metric("PDFs in library", n_pdfs)
    c2.metric("Already OCR'd", n_ocr)
    if n_pdfs > 0:
        st.info("➡️ Head to **🔍 OCR** to process the uploaded PDFs with MinerU.")

# ═════════════════════════════════════════════════════════════════════════════
# PDFs
# ═════════════════════════════════════════════════════════════════════════════
elif page == PAGES[2]:
    col_h, col_btn = st.columns([5, 1])
    with col_h:
        st.title("📁 PDF Library")
    with col_btn:
        st.write("")
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

    if not PDF_DIR.exists():
        st.error(f"Directory not found: `{PDF_DIR}`")
        st.stop()

    data = []
    for sub in sorted(PDF_DIR.iterdir(), key=lambda p: p.name):
        if not sub.is_dir():
            continue
        pdfs = sorted(sub.glob("*.pdf")) + sorted(sub.glob("*.PDF"))
        fname = pdfs[0].name if pdfs else "(no pdf)"
        done  = (OCR_OUT / sub.name).exists()
        data.append({"Ref #": sub.name, "Filename": fname[:90],
                     "OCR": "✅ Done" if done else "⬜ Pending"})

    n_done = sum(1 for d in data if "Done" in d["OCR"])
    st.caption(f"**{len(data)} PDFs** — {n_done} processed | {len(data)-n_done} pending")
    st.dataframe(
        pd.DataFrame(data),
        use_container_width=True,
        height=560,
        column_config={
            "Ref #":    st.column_config.TextColumn(width="small"),
            "Filename": st.column_config.TextColumn(width="large"),
            "OCR":      st.column_config.TextColumn(width="medium"),
        },
    )

# ═════════════════════════════════════════════════════════════════════════════
# OCR
# ═════════════════════════════════════════════════════════════════════════════
elif page == PAGES[3]:
    st.title("🔍 OCR — MinerU")
    st.info(
        "Runs `process_all.sh` inside the **mineru** container.  "
        "Input: `mineru/PDFs/files/<ref#>/<paper>.pdf` → "
        "Output: `mineru/output_images/<ref#>/auto/<ref#>.md`  "
        "Already-processed folders are skipped."
    )

    s = get_status()
    pct = s["n_ocr"] / max(s["n_pdfs"], 1)
    st.progress(pct, text=f"OCR progress: {s['n_ocr']}/{s['n_pdfs']} ({pct*100:.0f}%)")
    st.markdown("")

    if st.button("▶ Run OCR", type="primary"):
        rc = _run_stream(["docker", "exec", "-i", MINERU_CTR, "process_all.sh"])
        if rc == 0:
            st.success("OCR run complete!")
        else:
            st.error(f"process_all.sh exited with code {rc}")

    log_file = OCR_OUT / "ocr_run.log"
    if log_file.exists():
        st.markdown("---")
        with st.expander("📋 Last run log (ocr_run.log)", expanded=False):
            st.code(log_file.read_text(errors="replace")[-12000:], language="log")

# ═════════════════════════════════════════════════════════════════════════════
# ONTOLOGIES
# ═════════════════════════════════════════════════════════════════════════════
elif page == PAGES[4]:
    st.title("🧬 Ontologies")

    with st.expander("**Stage 01 — Extract ontologies from reference paper**", expanded=True):
        st.caption("Reads the reference MinerU markdown and generates structure + style ontology JSON files.")
        if st.button("▶ Run Stage 01", type="primary"):
            rc = _run_stream(_exec("01_extract_ontologies.py"))
            if rc == 0:
                st.success("Stage 01 complete — reload editors below.")

    st.markdown("---")
    tab1, tab2 = st.tabs(["📐  structure_ontology.json", "🎨  style_ontology.json"])

    with tab1:
        default = (STRUCT_JSON.read_text(encoding="utf-8")
                   if STRUCT_JSON.exists() else '{\n  "_note": "Run Stage 01 first"\n}')
        new_struct = st.text_area("struct", value=default, height=480,
                                  key="struct_editor", label_visibility="collapsed")
        if st.button("💾 Save structure_ontology.json", type="primary", key="save_struct"):
            try:
                json.loads(new_struct)
                STRUCT_JSON.parent.mkdir(parents=True, exist_ok=True)
                STRUCT_JSON.write_text(new_struct, encoding="utf-8")
                st.success("✅ Saved structure_ontology.json")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")

    with tab2:
        default2 = (STYLE_JSON.read_text(encoding="utf-8")
                    if STYLE_JSON.exists() else '{\n  "_note": "Run Stage 01 first"\n}')
        new_style = st.text_area("style", value=default2, height=480,
                                 key="style_editor", label_visibility="collapsed")
        if st.button("💾 Save style_ontology.json", type="primary", key="save_style"):
            try:
                json.loads(new_style)
                STYLE_JSON.parent.mkdir(parents=True, exist_ok=True)
                STYLE_JSON.write_text(new_style, encoding="utf-8")
                st.success("✅ Saved style_ontology.json")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")

# ═════════════════════════════════════════════════════════════════════════════
# GENERATE
# ═════════════════════════════════════════════════════════════════════════════
elif page == PAGES[5]:
    st.title("⚙️ Generate Paper")

    STAGES = [
        ("02", "02_plan_paper.py",       "Plan outline"),
        ("03", "03_agents_write.py",      "Agents write sections"),
        ("04", "04_validate.py",          "Validate draft"),
        ("05", "05_render_elsevier.py",   "Render Elsevier LaTeX"),
        ("06", "06_fix_latex.py",         "LLM LaTeX fix loop"),
        ("07", "07_generate_figures.py",  "Generate figures"),
    ]
    labels = [f"Stage {n} — {d}" for n, _, d in STAGES]

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        from_i = st.selectbox("From stage", range(len(STAGES)),
                              format_func=lambda i: labels[i], index=0)
    with c2:
        to_i = st.selectbox("To stage", range(len(STAGES)),
                            format_func=lambda i: labels[i], index=len(STAGES) - 1)
    with c3:
        st.write("")
        run_pipeline = st.button("▶ Run", type="primary", use_container_width=True)

    if run_pipeline:
        ran_ok = True
        for i, (num, script, desc) in enumerate(STAGES):
            if i < from_i or i > to_i:
                continue
            st.markdown(f"### Stage {num}: {desc}")
            rc = _run_stream(_exec(script))
            if rc != 0:
                st.error(f"Stage {num} failed (exit {rc}) — stopping.")
                ran_ok = False
                break
        if ran_ok:
            st.success("✅ Pipeline finished!")
            if FINAL_PDF.exists():
                st.balloons()

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("⚡ LaTeX Recompile")
        st.caption("pdflatex → bibtex → pdflatex × 2")
        if st.button("Recompile paper.tex"):
            if not (OUTPUT_DIR / "paper.tex").exists():
                st.error("paper.tex not found — run Stage 05 first.")
            else:
                for cmd in [
                    _latex_cmd("pdflatex", "-interaction=nonstopmode", "paper"),
                    _latex_cmd("bibtex", "paper"),
                    _latex_cmd("pdflatex", "-interaction=nonstopmode", "paper"),
                    _latex_cmd("pdflatex", "-interaction=nonstopmode", "paper"),
                ]:
                    _run_stream(cmd)
                if FINAL_PDF.exists():
                    st.success("PDF compiled successfully.")

    with col2:
        st.subheader("📥 Download")
        if FINAL_PDF.exists():
            size_mb = FINAL_PDF.stat().st_size / 1e6
            st.caption(f"paper.pdf — {size_mb:.1f} MB")
            with open(FINAL_PDF, "rb") as fh:
                st.download_button("📥 Download paper.pdf", fh, "paper.pdf",
                                   "application/pdf", type="primary",
                                   use_container_width=True)
        else:
            st.info("No PDF yet — run the pipeline first.")
