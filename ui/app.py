"""LLM-OCR Pipeline — Streamlit UI (Cupertino style)."""
from __future__ import annotations

import json
import os
import subprocess
import shutil
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LLM-OCR Pipeline",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Apple / Cupertino CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
/* System font stack — matches Apple SF Pro feel */
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue",
                 Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    font-size: 17px;
}

/* Sidebar — light gray, like macOS sidebar */
[data-testid="stSidebar"] {
    background: #f5f5f7 !important;
    border-right: 1px solid #e0e0e5;
}
[data-testid="stSidebar"] * { color: #1d1d1f !important; }

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stDecoration"] { display: none; }

/* Page headings — large Apple style */
h1 { font-size: 2.5rem !important; font-weight: 600; color: #1d1d1f;
     letter-spacing: -0.025em; margin-bottom: 0.4em !important; }
h2 { font-size: 1.6rem !important; font-weight: 600; color: #1d1d1f;
     letter-spacing: -0.015em; margin-top: 0.6em !important; }
h3 { font-size: 1.2rem !important; font-weight: 600; color: #1d1d1f; }

/* Body paragraphs */
p, li, label, [data-testid="stMarkdownContainer"] {
    font-size: 1rem; line-height: 1.5;
}

/* Muted caption text — slightly bigger, lighter */
.muted { color: #6e6e73; font-size: 0.95rem; line-height: 1.55;
         font-weight: 400; }

/* Clean separator */
.sep { border: none; border-top: 1px solid #e0e0e5; margin: 32px 0; }

/* Status row table */
.info-table { width: 100%; border-collapse: collapse; font-size: 1rem; }
.info-table td { padding: 13px 0; border-bottom: 1px solid #f2f2f7; color: #1d1d1f; }
.info-table td:first-child { color: #6e6e73; width: 38%; }
.info-table td:last-child  { color: #1d1d1f; font-weight: 500; }

/* Dot indicators */
.dot-ok  { display:inline-block; width:8px; height:8px; border-radius:50%;
            background:#34c759; margin-right:10px; }
.dot-no  { display:inline-block; width:8px; height:8px; border-radius:50%;
            background:#d1d1d6; margin-right:10px; }
.dot-run { display:inline-block; width:8px; height:8px; border-radius:50%;
            background:#ff9f0a; margin-right:10px; }

/* Stat blocks — Apple-large numerals */
.stat-row { display:flex; gap:48px; margin:12px 0 28px; }
.stat-block { }
.stat-num  { font-size:3rem; font-weight:600; color:#1d1d1f;
              letter-spacing:-0.035em; line-height:1; }
.stat-lbl  { font-size:0.88rem; color:#6e6e73; margin-top:6px; }

/* Progress bar (native Streamlit override) */
[data-testid="stProgressBar"] > div { background:#34c759 !important; }

/* Buttons — Apple-style */
button[kind="primary"] {
    background: #0071e3 !important;
    border: none !important;
    border-radius: 980px !important;
    font-size: 0.95rem !important;
    font-weight: 500 !important;
    padding: 9px 22px !important;
}
button[kind="secondary"] {
    background: transparent !important;
    border: 1px solid #d2d2d7 !important;
    border-radius: 980px !important;
    color: #0071e3 !important;
    font-size: 0.95rem !important;
    font-weight: 500 !important;
    padding: 9px 22px !important;
}

/* File uploader — minimal */
[data-testid="stFileUploader"] {
    background: #f5f5f7;
    border: 1.5px dashed #c7c7cc;
    border-radius: 14px;
    padding: 10px;
}

/* Nav items in sidebar — large Apple-style tap targets */
[data-testid="stSidebar"] [data-testid="stRadio"] > div {
    gap: 4px;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    font-size: 1.15rem !important;
    font-weight: 500 !important;
    padding: 12px 14px !important;
    border-radius: 10px !important;
    color: #1d1d1f !important;
    cursor: pointer;
    transition: background 0.15s ease;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: rgba(0,0,0,0.04);
}
[data-testid="stSidebar"] [data-testid="stRadio"] label > div:first-child {
    display: none !important;          /* hide the radio circle */
}

/* Dataframe */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKSPACE   = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
PDF_DIR     = WORKSPACE / "mineru" / "PDFs" / "files"
OCR_OUT     = WORKSPACE / "mineru" / "output_images"
PIPELINE    = WORKSPACE / "paper_generation"
ONTO_DIR    = PIPELINE / "ontologies"
OUTPUT_DIR  = PIPELINE / "output"
STRUCT_JSON = ONTO_DIR / "structure_ontology.json"
STYLE_JSON  = ONTO_DIR / "style_ontology.json"
FINAL_PDF   = OUTPUT_DIR / "paper.pdf"
BIB_FILE    = WORKSPACE / "mineru" / "PDFs" / "PDFs.bib"

MINERU_CTR  = os.environ.get("MINERU_CONTAINER",   "mineru")
PIPE_CTR    = os.environ.get("PIPELINE_CONTAINER", "llm-pipeline")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _exec(script: str) -> list[str]:
    return ["docker", "exec", "-i", "-w", "/workspace/paper_generation",
            PIPE_CTR, "python", "-u", script]


def _latex_cmd(*cmd: str) -> list[str]:
    return ["docker", "exec", "-i", "-w", "/workspace/paper_generation/output",
            PIPE_CTR, *cmd]


def _run_stream(cmd: list[str]) -> int:
    """Run cmd, stream output. Polls session_state["stop_requested"] to allow cancel.
    Records PID so the sidebar Stop button (from another tab/session) can kill it."""
    box = st.empty()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert proc.stdout

    # Record PID so external Stop can target it
    pid_file = Path("/tmp/llm_ui_running.pid")
    pid_file.write_text(str(proc.pid))

    log = "$ " + " ".join(cmd) + "\n"
    try:
        for line in proc.stdout:
            log += line
            box.code(log[-8000:], language="bash")
            if st.session_state.get("stop_requested"):
                proc.terminate()
                log += "\n[stopped by user]"
                break
        proc.wait()
    finally:
        if pid_file.exists():
            pid_file.unlink()
        st.session_state["stop_requested"] = False

    log += f"\n[exit {proc.returncode}]"
    box.code(log[-8000:], language="bash")
    return proc.returncode


def _kill_running() -> str:
    """Kill anything currently running. Called from sidebar Stop button.
    Works across sessions because PID is written to /tmp/llm_ui_running.pid."""
    msgs = []
    pid_file = Path("/tmp/llm_ui_running.pid")
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 15)   # SIGTERM
            msgs.append(f"sent SIGTERM to PID {pid}")
        except (ProcessLookupError, ValueError):
            msgs.append("no live PID")
        pid_file.unlink(missing_ok=True)

    # Also kill anything still running inside the worker containers
    for ctr, pat in [(MINERU_CTR, "process_all"), (PIPE_CTR, "python")]:
        r = subprocess.run(
            ["docker", "exec", ctr, "pkill", "-f", pat],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            msgs.append(f"killed `{pat}` in {ctr}")

    st.session_state["stop_requested"] = True
    return " · ".join(msgs) if msgs else "nothing was running"


# ── Ontology graph builders ───────────────────────────────────────────────────
# Role → fill color (muted, Apple-palette)
_ROLE_COLOR: dict[str, str] = {
    "abstract":    "#dbeafe",   # blue-50
    "motivation":  "#fef3c7",   # amber-100
    "background":  "#ede9fe",   # violet-100
    "methods":     "#dcfce7",   # green-100
    "results":     "#fee2e2",   # red-100
    "conclusion":  "#ccfbf1",   # teal-100
    "discussion":  "#fce7f3",   # pink-100
}
_DEFAULT_COLOR = "#f5f5f7"


def _esc(s: str) -> str:
    """Escape a string for use in a DOT label."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _struct_dot_nodes(nodes: list, lines: list, parent_id: str | None = None) -> None:
    for n in nodes:
        nid   = n.get("id", "?")
        title = _esc(n.get("title", nid))
        role  = n.get("role", "")
        wc    = n.get("word_count", 0)
        color = _ROLE_COLOR.get(role, _DEFAULT_COLOR)
        label = f"{title}\\n{role}  ·  {wc}w"
        lines.append(
            f'  "{nid}" [label="{label}" style=filled fillcolor="{color}" '
            f'fontname="Helvetica Neue,Arial" fontsize=11 '
            f'shape=box width=2.2 height=0.55];'
        )
        if parent_id:
            lines.append(f'  "{parent_id}" -> "{nid}";')
        _struct_dot_nodes(n.get("children", []), lines, nid)


def build_structure_dot(data: dict) -> str:
    lines = [
        'digraph Structure {',
        '  graph [rankdir=LR splines=ortho bgcolor="#ffffff" '
        '         fontname="Helvetica Neue,Arial" pad=0.5];',
        '  node  [fontname="Helvetica Neue,Arial" fontsize=11 '
        '         color="#c7c7cc" penwidth=1.2];',
        '  edge  [color="#c7c7cc" arrowsize=0.7 penwidth=1];',
    ]
    _struct_dot_nodes(data.get("tree", []), lines)
    lines.append("}")
    return "\n".join(lines)


def build_style_dot(data: dict) -> str:
    lines = [
        'graph Style {',
        '  graph [layout=neato overlap=false bgcolor="#ffffff" '
        '         fontname="Helvetica Neue,Arial" pad=0.8];',
        '  node  [fontname="Helvetica Neue,Arial" fontsize=11 '
        '         style=filled color="#c7c7cc" penwidth=1.2];',
        '  edge  [color="#c7c7cc" penwidth=1];',
        '  "Style" [shape=circle fillcolor="#1d1d1f" fontcolor="#ffffff" '
        '           fontsize=13 width=1.4];',
    ]

    # scalar properties → direct children
    scalars = {
        "voice":          data.get("voice", ""),
        "tense":          data.get("tense_dominant", ""),
        "hedging":        data.get("hedging_frequency", ""),
        "citation style": data.get("citation_style", ""),
        "sentence len":   str(data.get("average_sentence_length", "")),
        "terminology":    data.get("domain_terminology_density", ""),
    }
    for prop, val in scalars.items():
        if not val:
            continue
        pid = f"prop_{prop}"
        lines.append(
            f'  "{pid}" [label="{_esc(prop)}" shape=ellipse '
            f'fillcolor="#f5f5f7" fontsize=11];'
        )
        vid = f"val_{prop}"
        lines.append(
            f'  "{vid}" [label="{_esc(val)}" shape=box '
            f'fillcolor="#dbeafe" fontsize=10];'
        )
        lines.append(f'  "Style" -- "{pid}";')
        lines.append(f'  "{pid}" -- "{vid}";')

    # list properties → show up to 5 items
    list_props = [
        ("hedging markers",  "hedging_markers",   "#fef3c7"),
        ("transitions",      "transition_markers", "#dcfce7"),
        ("evidence frames",  "evidence_frames",    "#ede9fe"),
    ]
    for label, key, color in list_props:
        items = data.get(key, [])[:5]
        if not items:
            continue
        gid = f"group_{key}"
        lines.append(
            f'  "{gid}" [label="{_esc(label)}" shape=ellipse '
            f'fillcolor="#f5f5f7" fontsize=11];'
        )
        lines.append(f'  "Style" -- "{gid}";')
        for i, item in enumerate(items):
            iid = f"item_{key}_{i}"
            short = _esc(item[:42] + ("…" if len(item) > 42 else ""))
            lines.append(
                f'  "{iid}" [label="{short}" shape=box '
                f'fillcolor="{color}" fontsize=9];'
            )
            lines.append(f'  "{gid}" -- "{iid}";')

    # rhetorical moves → cluster per move
    rhetorical = data.get("rhetorical_moves", {})
    if rhetorical:
        lines.append(
            '  "rhetorical moves" [shape=ellipse fillcolor="#f5f5f7" fontsize=11];'
        )
        lines.append('  "Style" -- "rhetorical moves";')
        for move, examples in rhetorical.items():
            mid = f"move_{move}"
            lines.append(
                f'  "{mid}" [label="{_esc(move)}" shape=box '
                f'fillcolor="#fee2e2" fontsize=10];'
            )
            lines.append(f'  "rhetorical moves" -- "{mid}";')

    lines.append("}")
    return "\n".join(lines)


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


def _dot(ok: bool, running: bool = False) -> str:
    cls = "dot-run" if running else ("dot-ok" if ok else "dot-no")
    return f'<span class="{cls}"></span>'


# ── Ontology tree flatten (for interactive picker) ────────────────────────────
def flatten_structure(nodes: list, depth: int = 0,
                      path: list | None = None) -> list[dict]:
    """Return flat list of {id, label, depth, node, breadcrumb} for selectbox."""
    out: list[dict] = []
    path = path or []
    for n in nodes:
        nid = n.get("id", "?")
        title = n.get("title", nid)
        crumb = path + [title]
        indent = "    " * depth
        out.append({
            "id": nid,
            "label": f'{indent}{title}',
            "depth": depth,
            "node": n,
            "breadcrumb": " › ".join(crumb),
        })
        out.extend(flatten_structure(n.get("children", []),
                                     depth + 1, crumb))
    return out


def render_section_card(node: dict, breadcrumb: str) -> None:
    """Render a section node's attributes as a Cupertino-style detail card."""
    role = node.get("role", "—")
    color = _ROLE_COLOR.get(role, _DEFAULT_COLOR)
    st.markdown(
        f'<div style="background:{color};border-radius:14px;padding:18px 22px;'
        f'margin-top:8px">'
        f'<p style="margin:0;color:#6e6e73;font-size:0.78rem">{breadcrumb}</p>'
        f'<h3 style="margin:4px 0 12px 0">{node.get("title","")}</h3>'
        f'<table class="info-table"><tbody>'
        f'<tr><td>role</td><td>{role}</td></tr>'
        f'<tr><td>level</td><td>{node.get("level","—")}</td></tr>'
        f'<tr><td>word count</td><td>{node.get("word_count",0)}</td></tr>'
        f'<tr><td>citations</td><td>{node.get("citation_count",0)}</td></tr>'
        f'<tr><td>has table</td><td>{"yes" if node.get("has_table") else "no"}</td></tr>'
        f'<tr><td>has figure</td><td>{"yes" if node.get("has_figure") else "no"}</td></tr>'
        f'<tr><td>children</td><td>{len(node.get("children",[]))}</td></tr>'
        f'</tbody></table>'
        f'</div>',
        unsafe_allow_html=True,
    )
    purpose = node.get("purpose", "")
    if purpose:
        st.markdown(f'<p class="muted" style="margin-top:14px"><b>Purpose</b></p>',
                    unsafe_allow_html=True)
        st.markdown(f'<p style="margin-top:0">{purpose}</p>',
                    unsafe_allow_html=True)
    ev = node.get("expected_evidence", [])
    if ev:
        st.markdown('<p class="muted" style="margin-top:8px"><b>Expected evidence</b></p>',
                    unsafe_allow_html=True)
        st.markdown(
            "".join(f'<span style="background:#f5f5f7;border-radius:980px;'
                    f'padding:3px 12px;margin-right:6px;font-size:0.82rem">'
                    f'{e}</span>' for e in ev),
            unsafe_allow_html=True,
        )
    rqs = node.get("research_questions_addressed", [])
    if rqs:
        st.markdown('<p class="muted" style="margin-top:14px"><b>Research questions</b></p>',
                    unsafe_allow_html=True)
        for q in rqs:
            st.markdown(f'- {q}')
    preview = node.get("preview", "")
    if preview:
        st.markdown('<p class="muted" style="margin-top:8px"><b>Preview</b></p>',
                    unsafe_allow_html=True)
        st.markdown(f'<p style="color:#3a3a3c;font-style:italic">'
                    f'"{preview}…"</p>', unsafe_allow_html=True)


def render_style_card(key: str, value) -> None:
    """Render a style property (scalar or list)."""
    st.markdown(
        f'<div style="background:#f5f5f7;border-radius:14px;padding:18px 22px;'
        f'margin-top:8px">'
        f'<p style="margin:0;color:#6e6e73;font-size:0.78rem">style property</p>'
        f'<h3 style="margin:4px 0 12px 0">{key}</h3>',
        unsafe_allow_html=True,
    )
    if isinstance(value, dict):
        for k, v in value.items():
            st.markdown(f'**{k}**')
            if isinstance(v, list):
                for item in v:
                    st.markdown(f'- {item}')
            else:
                st.markdown(f'- {v}')
    elif isinstance(value, list):
        for item in value:
            st.markdown(f'- {item}')
    else:
        st.markdown(f'<p style="font-size:1.1rem;font-weight:500">{value}</p>',
                    unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
PAGES = ["Status", "Import", "Library", "OCR", "Ontologies", "Generate"]
PAGE_ICONS = {
    "Status":     "◐",
    "Import":     "↥",
    "Library":    "≣",
    "OCR":        "⊕",
    "Ontologies": "✦",
    "Generate":   "▶",
}

if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = "Status"

def nav_to(target: str):
    """Jump to another page from inside any page body."""
    if target in PAGES:
        st.session_state["nav_page"] = target
        st.rerun()

def render_jump_bar(current: str):
    """Render a row of always-visible page-jump buttons (no Next/Prev).
    Skips the current page so users see only where they can go."""
    targets = [p for p in PAGES if p != current]
    cols = st.columns(len(targets))
    for col, p in zip(cols, targets):
        with col:
            if st.button(f"{PAGE_ICONS[p]}  {p}",
                         key=f"jump_{current}_{p}",
                         use_container_width=True):
                nav_to(p)

with st.sidebar:
    st.markdown(
        '<p style="font-size:1.1rem;font-weight:700;color:#1d1d1f;'
        'letter-spacing:-0.02em;margin-bottom:2px">LLM-OCR</p>'
        '<p style="font-size:0.78rem;color:#6e6e73;margin-top:0">PDF Pipeline</p>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr class="sep" style="margin:12px 0">', unsafe_allow_html=True)
    page = st.radio("", PAGES, label_visibility="collapsed",
                    key="nav_page",
                    index=PAGES.index(st.session_state["nav_page"]))
    st.markdown('<hr class="sep" style="margin:12px 0">', unsafe_allow_html=True)

    s = get_status()
    pct = s["n_ocr"] / max(s["n_pdfs"], 1)
    st.markdown(
        f'<p class="muted">OCR &nbsp;<b style="color:#1d1d1f">'
        f'{s["n_ocr"]}</b> / {s["n_pdfs"]}</p>',
        unsafe_allow_html=True,
    )
    st.progress(pct)

    # ── Always-visible Stop button ────────────────────────────────────────────
    st.markdown('<hr class="sep" style="margin:16px 0 8px">',
                unsafe_allow_html=True)
    running = Path("/tmp/llm_ui_running.pid").exists()
    status_html = (
        '<b style="color:#ff9f0a">●</b> Task running'
        if running else
        '<b style="color:#34c759">●</b> Idle'
    )
    st.markdown(
        f'<p class="muted">{status_html}</p>',
        unsafe_allow_html=True,
    )
    if st.button("Stop running task", type="secondary",
                 use_container_width=True, key="sidebar_stop"):
        msg = _kill_running()
        st.toast(msg)


# ═════════════════════════════════════════════════════════════════════════════
# STATUS
# ═════════════════════════════════════════════════════════════════════════════
if page == "Status":
    col_h, col_btn = st.columns([6, 1])
    with col_h:
        st.markdown("# Status")
    with col_btn:
        st.write("")
        if st.button("Refresh", type="secondary"):
            st.rerun()

    s = get_status()
    pct = s["n_ocr"] / max(s["n_pdfs"], 1)

    st.markdown(
        f'<div class="stat-row">'
        f'<div class="stat-block"><div class="stat-num">{s["n_pdfs"]}</div>'
        f'<div class="stat-lbl">PDFs in library</div></div>'
        f'<div class="stat-block"><div class="stat-num">{s["n_ocr"]}</div>'
        f'<div class="stat-lbl">OCR complete</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.progress(pct)
    st.markdown(f'<p class="muted" style="margin-top:6px">'
                f'{pct*100:.0f}% of papers parsed by MinerU</p>',
                unsafe_allow_html=True)

    st.markdown('<hr class="sep">', unsafe_allow_html=True)
    st.markdown("## Pipeline steps")

    ocr_running = 0 < s["n_ocr"] < s["n_pdfs"]
    steps = [
        ("PDFs imported",      s["n_pdfs"] > 0,  False,       f"{s['n_pdfs']} papers in library"),
        ("Bibliography",       s["bib"],          False,       "PDFs.bib"),
        ("OCR",                s["n_ocr"] >= s["n_pdfs"] and s["n_pdfs"] > 0,
                               ocr_running,       f"{s['n_ocr']}/{s['n_pdfs']} papers"),
        ("Structure ontology", s["struct"],        False,       "structure_ontology.json"),
        ("Style ontology",     s["style"],         False,       "style_ontology.json"),
        ("Outline",            s["outline"],       False,       "outline.json"),
        ("Draft",              s["draft"],         False,       "draft_sections.json"),
        ("LaTeX",              s["tex"],           False,       "paper.tex"),
        ("PDF",                s["pdf"],           False,       "paper.pdf"),
    ]
    rows = "".join(
        f"<tr><td>{_dot(done, running)}{label}</td>"
        f'<td style="color:#6e6e73">{detail}</td></tr>'
        for label, done, running, detail in steps
    )
    st.markdown(
        f'<table class="info-table"><tbody>{rows}</tbody></table>',
        unsafe_allow_html=True,
    )


# ═════════════════════════════════════════════════════════════════════════════
# IMPORT
# ═════════════════════════════════════════════════════════════════════════════
elif page == "Import":
    st.markdown("# Import from Zotero")
    st.markdown(
        '<p class="muted">Export your Zotero collection as BibTeX + files. '
        'Drop the <b>.bib</b> file and the accompanying PDFs here. '
        'The folder structure from Zotero\'s "Export Files" is preserved automatically.</p>',
        unsafe_allow_html=True,
    )

    st.markdown('<hr class="sep">', unsafe_allow_html=True)

    # ── BIB ──────────────────────────────────────────────────────────────────
    st.markdown("## Bibliography")
    st.markdown(
        '<p class="muted">The <code>.bib</code> file from Zotero → '
        'File → Export Library → BibTeX.</p>',
        unsafe_allow_html=True,
    )
    bib_up = st.file_uploader(
        "Drop .bib file here",
        type=["bib"],
        key="bib_uploader",
        label_visibility="collapsed",
    )
    if bib_up is not None:
        dest_bib = WORKSPACE / "mineru" / "PDFs" / "PDFs.bib"
        dest_bib.parent.mkdir(parents=True, exist_ok=True)
        dest_bib.write_bytes(bib_up.getbuffer())
        n_entries = bib_up.getvalue().decode("utf-8", errors="ignore").count("@")
        st.markdown(
            f'<p class="muted" style="margin-top:8px">Saved — '
            f'{n_entries} entries, {len(bib_up.getvalue())//1024} KB</p>',
            unsafe_allow_html=True,
        )
    elif BIB_FILE.exists():
        n_bib = BIB_FILE.read_text(errors="ignore").count("@")
        st.markdown(
            f'<p class="muted" style="margin-top:4px">'
            f'Current library: {n_bib} entries · '
            f'{BIB_FILE.stat().st_size//1024} KB</p>',
            unsafe_allow_html=True,
        )

    st.markdown('<hr class="sep">', unsafe_allow_html=True)

    # ── PDFs ─────────────────────────────────────────────────────────────────
    st.markdown("## PDFs")
    st.markdown(
        '<p class="muted">Select all PDFs from the Zotero "files" folder. '
        'Each file is stored under <code>mineru/PDFs/files/&lt;citekey&gt;/</code> '
        'matching Zotero\'s export layout.</p>',
        unsafe_allow_html=True,
    )
    pdf_ups = st.file_uploader(
        "Drop PDF files here",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_uploader",
        label_visibility="collapsed",
    )
    if pdf_ups:
        dest_root = WORKSPACE / "mineru" / "PDFs" / "files"
        dest_root.mkdir(parents=True, exist_ok=True)
        saved, skipped = [], []
        for uf in pdf_ups:
            slug = uf.name.replace(" ", "_")[:40].rstrip("_")
            slug = "".join(c for c in slug if c.isalnum() or c in "_-.") or "paper"
            slug = Path(slug).stem
            folder = dest_root / slug
            folder.mkdir(exist_ok=True)
            dest_pdf = folder / uf.name
            if dest_pdf.exists():
                skipped.append(uf.name)
            else:
                dest_pdf.write_bytes(uf.getbuffer())
                saved.append(uf.name)

        if saved:
            st.markdown(
                f'<p class="muted" style="margin-top:8px">'
                f'{len(saved)} file{"s" if len(saved)!=1 else ""} added'
                + (f" · {len(skipped)} already present" if skipped else "")
                + "</p>",
                unsafe_allow_html=True,
            )

    st.markdown('<hr class="sep">', unsafe_allow_html=True)

    n_pdfs = sum(1 for p in PDF_DIR.iterdir() if p.is_dir()) if PDF_DIR.exists() else 0
    if n_pdfs > 0:
        st.markdown(
            f'<p class="muted">{n_pdfs} papers in library · '
            f'continue in <b>OCR</b>.</p>',
            unsafe_allow_html=True,
        )

    # ── Danger zone: clear library ───────────────────────────────────────────
    st.markdown('<hr class="sep">', unsafe_allow_html=True)
    st.markdown("## Start over")
    st.markdown(
        '<p class="muted">Importing more files always <b>adds</b> to the '
        'existing library (PDFs of the same name are skipped). '
        'Use this to wipe everything and start from zero.</p>',
        unsafe_allow_html=True,
    )

    confirm = st.checkbox(
        "I understand this will permanently delete all PDFs, the .bib file, "
        "and all OCR results.",
        key="confirm_clear",
    )
    c_a, c_b = st.columns([1, 4])
    with c_a:
        if st.button("Clear everything", type="secondary",
                     disabled=not confirm, use_container_width=True):
            removed = []
            for target in [PDF_DIR, OCR_OUT, BIB_FILE]:
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
                    removed.append(target.name)
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            OCR_OUT.mkdir(parents=True, exist_ok=True)
            st.toast(f"Cleared: {', '.join(removed) or 'nothing'}")
            st.session_state["confirm_clear"] = False
            st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# LIBRARY
# ═════════════════════════════════════════════════════════════════════════════
elif page == "Library":
    col_h, col_btn = st.columns([6, 1])
    with col_h:
        st.markdown("# Library")
    with col_btn:
        st.write("")
        if st.button("Refresh", type="secondary"):
            st.rerun()

    if not PDF_DIR.exists():
        st.markdown(
            f'<p class="muted">No PDFs yet. Import them first.</p>',
            unsafe_allow_html=True,
        )
        st.stop()

    data = []
    for sub in sorted(PDF_DIR.iterdir(), key=lambda p: p.name):
        if not sub.is_dir():
            continue
        pdfs = sorted(sub.glob("*.pdf")) + sorted(sub.glob("*.PDF"))
        fname = pdfs[0].name if pdfs else ""
        done  = (OCR_OUT / sub.name).exists()
        data.append({"Reference": sub.name, "File": fname[:80],
                     "OCR": "done" if done else "pending"})

    n_done = sum(1 for d in data if d["OCR"] == "done")
    st.markdown(
        f'<p class="muted">{len(data)} papers · {n_done} OCR\'d · '
        f'{len(data)-n_done} pending</p>',
        unsafe_allow_html=True,
    )
    st.dataframe(
        pd.DataFrame(data),
        use_container_width=True,
        height=560,
        column_config={
            "Reference": st.column_config.TextColumn(width="small"),
            "File":      st.column_config.TextColumn(width="large"),
            "OCR":       st.column_config.TextColumn(width="small"),
        },
    )


# ═════════════════════════════════════════════════════════════════════════════
# OCR
# ═════════════════════════════════════════════════════════════════════════════
elif page == "OCR":
    st.markdown("# OCR")
    s = get_status()
    pct = s["n_ocr"] / max(s["n_pdfs"], 1)
    st.markdown(
        f'<p class="muted">{s["n_ocr"]} of {s["n_pdfs"]} papers processed '
        f'({pct*100:.0f}%) · Already-processed papers are skipped automatically.</p>',
        unsafe_allow_html=True,
    )
    st.progress(pct)
    st.markdown("")

    if st.button("Run OCR", type="primary"):
        rc = _run_stream(["docker", "exec", "-i", MINERU_CTR, "process_all.sh"])
        if rc == 0:
            st.markdown('<p class="muted">Completed.</p>', unsafe_allow_html=True)
        else:
            st.error(f"process_all.sh exited with code {rc}")

    log_file = OCR_OUT / "ocr_run.log"
    if log_file.exists():
        st.markdown('<hr class="sep">', unsafe_allow_html=True)
        with st.expander("Last run log", expanded=False):
            st.code(log_file.read_text(errors="replace")[-12000:], language="log")


# ═════════════════════════════════════════════════════════════════════════════
# ONTOLOGIES
# ═════════════════════════════════════════════════════════════════════════════
elif page == "Ontologies":
    st.markdown("# Ontologies")
    st.markdown(
        '<p class="muted">Extract structure and style patterns from the reference '
        'paper to guide section planning and writing.</p>',
        unsafe_allow_html=True,
    )

    st.markdown('<hr class="sep">', unsafe_allow_html=True)
    with st.expander("Stage 01 — extract from reference paper", expanded=True):
        if st.button("Run Stage 01", type="primary"):
            rc = _run_stream(_exec("01_extract_ontologies.py"))
            if rc == 0:
                st.markdown('<p class="muted">Done.</p>', unsafe_allow_html=True)

    st.markdown('<hr class="sep">', unsafe_allow_html=True)
    tab_graph, tab1, tab2 = st.tabs(["Explorer", "structure_ontology.json", "style_ontology.json"])

    # ── Graph / Explorer tab ──────────────────────────────────────────────────
    with tab_graph:
        has_struct = STRUCT_JSON.exists()
        has_style  = STYLE_JSON.exists()

        if not has_struct and not has_style:
            st.markdown(
                '<p class="muted">Run Stage 01 to generate the ontologies first.</p>',
                unsafe_allow_html=True,
            )
        else:
            sub_struct, sub_style = st.tabs(["Structure", "Style"])

            # ── STRUCTURE explorer ────────────────────────────────────────────
            with sub_struct:
                if not has_struct:
                    st.markdown('<p class="muted">Not generated yet.</p>',
                                unsafe_allow_html=True)
                else:
                    struct_data = json.loads(STRUCT_JSON.read_text(encoding="utf-8"))
                    flat = flatten_structure(struct_data.get("tree", []))

                    g_col, d_col = st.columns([3, 2])
                    with g_col:
                        st.markdown('<p class="muted">Overview — color by role</p>',
                                    unsafe_allow_html=True)
                        st.graphviz_chart(build_structure_dot(struct_data),
                                          use_container_width=True)
                    with d_col:
                        st.markdown('<p class="muted">Navigate sections</p>',
                                    unsafe_allow_html=True)
                        labels = [f['label'] for f in flat]
                        ids    = [f['id']    for f in flat]
                        idx = st.selectbox(
                            "section",
                            range(len(flat)),
                            format_func=lambda i: labels[i],
                            label_visibility="collapsed",
                            key="struct_sel",
                        )
                        if idx is not None:
                            f = flat[idx]
                            render_section_card(f["node"], f["breadcrumb"])

            # ── STYLE explorer ────────────────────────────────────────────────
            with sub_style:
                if not has_style:
                    st.markdown('<p class="muted">Not generated yet.</p>',
                                unsafe_allow_html=True)
                else:
                    style_data = json.loads(STYLE_JSON.read_text(encoding="utf-8"))

                    g_col, d_col = st.columns([3, 2])
                    with g_col:
                        st.markdown('<p class="muted">Overview — hub of properties</p>',
                                    unsafe_allow_html=True)
                        st.graphviz_chart(build_style_dot(style_data),
                                          use_container_width=True)
                    with d_col:
                        st.markdown('<p class="muted">Navigate properties</p>',
                                    unsafe_allow_html=True)
                        # filter out 'source' meta key
                        keys = [k for k in style_data.keys() if k != "source"]
                        sel = st.selectbox(
                            "property",
                            keys,
                            label_visibility="collapsed",
                            key="style_sel",
                        )
                        if sel:
                            render_style_card(sel, style_data[sel])

    # ── JSON editor tabs ──────────────────────────────────────────────────────
    with tab1:
        default = (STRUCT_JSON.read_text(encoding="utf-8")
                   if STRUCT_JSON.exists() else '{\n  "_note": "Run Stage 01 first"\n}')
        new_struct = st.text_area("", value=default, height=480,
                                  key="struct_editor", label_visibility="collapsed")
        if st.button("Save", type="primary", key="save_struct"):
            try:
                json.loads(new_struct)
                STRUCT_JSON.parent.mkdir(parents=True, exist_ok=True)
                STRUCT_JSON.write_text(new_struct, encoding="utf-8")
                st.markdown('<p class="muted">Saved.</p>', unsafe_allow_html=True)
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON — {e}")

    with tab2:
        default2 = (STYLE_JSON.read_text(encoding="utf-8")
                    if STYLE_JSON.exists() else '{\n  "_note": "Run Stage 01 first"\n}')
        new_style = st.text_area("", value=default2, height=480,
                                 key="style_editor", label_visibility="collapsed")
        if st.button("Save", type="primary", key="save_style"):
            try:
                json.loads(new_style)
                STYLE_JSON.parent.mkdir(parents=True, exist_ok=True)
                STYLE_JSON.write_text(new_style, encoding="utf-8")
                st.markdown('<p class="muted">Saved.</p>', unsafe_allow_html=True)
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON — {e}")


# ═════════════════════════════════════════════════════════════════════════════
# GENERATE
# ═════════════════════════════════════════════════════════════════════════════
elif page == "Generate":
    st.markdown("# Generate paper")
    st.markdown(
        '<p class="muted">Run pipeline stages to plan, write, validate, '
        'and render the paper as a PDF.</p>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr class="sep">', unsafe_allow_html=True)

    STAGES = [
        ("02", "02_plan_paper.py",      "Plan outline"),
        ("03", "03_agents_write.py",    "Write sections"),
        ("04", "04_validate.py",        "Validate draft"),
        ("05", "05_render_elsevier.py", "Render LaTeX"),
        ("06", "06_fix_latex.py",       "Fix LaTeX"),
        ("07", "07_generate_figures.py","Generate figures"),
    ]
    labels = [f"{n}  {d}" for n, _, d in STAGES]

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        from_i = st.selectbox("From", range(len(STAGES)),
                              format_func=lambda i: labels[i], index=0)
    with c2:
        to_i = st.selectbox("To", range(len(STAGES)),
                            format_func=lambda i: labels[i], index=len(STAGES)-1)
    with c3:
        st.write("")
        run_pipeline = st.button("Run", type="primary", use_container_width=True)

    if run_pipeline:
        ran_ok = True
        for i, (num, script, desc) in enumerate(STAGES):
            if i < from_i or i > to_i:
                continue
            st.markdown(f"### {num} — {desc}")
            rc = _run_stream(_exec(script))
            if rc != 0:
                st.error(f"Stage {num} failed (exit {rc})")
                ran_ok = False
                break
        if ran_ok:
            st.markdown('<p class="muted">Pipeline finished.</p>',
                        unsafe_allow_html=True)

    st.markdown('<hr class="sep">', unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("## Recompile LaTeX")
        st.markdown(
            '<p class="muted">pdflatex → bibtex → pdflatex × 2</p>',
            unsafe_allow_html=True,
        )
        if st.button("Recompile", type="secondary"):
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

    with col2:
        st.markdown("## Download")
        if FINAL_PDF.exists():
            size_mb = FINAL_PDF.stat().st_size / 1e6
            st.markdown(
                f'<p class="muted">paper.pdf · {size_mb:.1f} MB</p>',
                unsafe_allow_html=True,
            )
            with open(FINAL_PDF, "rb") as fh:
                st.download_button(
                    "Download PDF", fh, "paper.pdf", "application/pdf",
                    type="primary", use_container_width=True,
                )
        else:
            st.markdown(
                '<p class="muted">No PDF yet. Run the pipeline first.</p>',
                unsafe_allow_html=True,
            )
