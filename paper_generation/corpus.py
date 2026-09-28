"""Corpus loader: builds the evidence corpus from ALL parsed papers + bib metadata.

Sources:
  - mineru/output_images/<citekey>/auto/<citekey>.md   (MinerU parsed full-text)
  - mineru/initial_bib/_enriched/*.txt                 (BibTeX with citekeys RN1, RN100...)

Returns:
  - bib_index    : {citekey: {title, author, year, doi, journal, abstract}}
  - corpus       : list of {citekey, chunk_id, text}  (paragraph-sized chunks)

Usage from other scripts:
    from corpus import load_bib_index, load_corpus
"""
from __future__ import annotations
import json
import re
from pathlib import Path

# Resolve repo root relative to this file so it works both on the host and
# inside Docker containers (where the repo is mounted at /workspace).
REPO     = Path(__file__).resolve().parent.parent
PARSED   = REPO / "mineru" / "output_images"

# Bib sources searched in order; all found files are merged.
# Single authoritative bib — Zotero export in mineru/PDFs/PDFs.bib
# Legacy bk.initial_bib is intentionally excluded; OCR text comes
# exclusively from mineru/output_images/.
_BIB_SOURCES = [
    REPO / "mineru" / "PDFs" / "PDFs.bib",
]

ENTRY_RE = re.compile(
    r"@\w+\s*\{\s*(?P<key>[^,\s]+)\s*,(?P<body>.*?)\n\}\s*",
    re.DOTALL,
)
FIELD_RE = re.compile(r"(\w+)\s*=\s*\{(.*?)\}\s*,?\s*$", re.MULTILINE | re.DOTALL)


def _parse_bib_file(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in ENTRY_RE.finditer(text):
        key = m.group("key").strip()
        body = m.group("body")
        fields = {f.group(1).lower(): f.group(2).strip()
                  for f in FIELD_RE.finditer(body + "\n")}
        out[key] = {
            "title":    fields.get("title", ""),
            "author":   fields.get("author", ""),
            "year":     fields.get("year", ""),
            "doi":      fields.get("doi", ""),
            "journal":  fields.get("journal", ""),
            "abstract": fields.get("abstract", ""),
        }
    return out


def _ocr_keys() -> set[str]:
    """Set of canonical Zotero citekeys for which we have OCR'd full-text.

    Each ``mineru/output_images/<folder>/auto/<folder>.md`` is resolved to its
    BibTeX key via the ``file = {…files/<folder>/…}`` entry in PDFs.bib. Folders
    without a matching bib entry are returned under their raw folder name as a
    fallback (legacy behaviour, used only when PDFs.bib is missing the file
    reference).
    """
    if not PARSED.exists():
        return set()
    folders = {p.name for p in PARSED.iterdir() if p.is_dir()
               and (p / "auto" / f"{p.name}.md").exists()}
    f2k = folder_to_bibkey()
    return {f2k.get(folder, folder) for folder in folders}


_FILE_FOLDER_RE = re.compile(r"files/(\d+)/", re.MULTILINE)


def folder_to_bibkey() -> dict[str, str]:
    """Map OCR folder names → BibTeX citekeys from PDFs.bib.

    Zotero exports include a ``file = {…:files/<NUM>/…}`` field for each entry.
    The numeric ``<NUM>`` matches a sub-directory under ``mineru/output_images``.
    Returns ``{"1790": "roux_current_1994", …}``.
    """
    mapping: dict[str, str] = {}
    for src in _BIB_SOURCES:
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8", errors="ignore")
        # Iterate entries the same way _parse_bib_file does.
        for m in ENTRY_RE.finditer(text):
            key = m.group("key").strip()
            body = m.group("body")
            for fm in _FILE_FOLDER_RE.finditer(body):
                mapping.setdefault(fm.group(1), key)
    return mapping


def load_bib_index(restrict_to_ocr: bool = True) -> dict[str, dict]:
    """Merged citekey → metadata across all bib sources.

    Sources checked in order:
      1. mineru/PDFs/PDFs.bib          (Zotero export — canonical)
      2. mineru/bk.initial_bib/_enriched/*.txt  (legacy enriched bibs)

    If restrict_to_ocr is True (default), only return entries whose citekey
    has been OCR'd (i.e. a folder exists in output_images/). This ensures
    that every cited paper has retrievable full-text evidence and that the
    writer cannot cite non-OCR'd references.
    """
    index: dict[str, dict] = {}
    for f in _BIB_SOURCES:
        if f.exists():
            index.update(_parse_bib_file(f.read_text(encoding="utf-8", errors="ignore")))
    if restrict_to_ocr:
        ocr = _ocr_keys()
        f2k = folder_to_bibkey()
        # An entry is kept if either (a) its citekey matches an OCR folder
        # directly, or (b) it references an OCR'd folder via files/<NUM>/.
        keep_keys = {k for k in index if k in ocr} | {
            bk for folder, bk in f2k.items() if folder in ocr
        }
        index = {k: v for k, v in index.items() if k in keep_keys}
    return index


def _chunk(text: str, size: int = 700) -> list[str]:
    paras = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 80]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) > size:
            if buf:
                chunks.append(buf)
            buf = p
        else:
            buf = (buf + "\n\n" + p) if buf else p
    if buf:
        chunks.append(buf)
    return chunks


def load_corpus(
    exclude: set[str] | None = None,
    bib_index: dict[str, dict] | None = None,
) -> list[dict]:
    """Chunked full-text of every parsed paper (excluding any in `exclude`).
    Each chunk is tagged with:
      - citekey:   canonical Zotero BibTeX key (e.g. ``patel_development_2025``),
                   resolved from the OCR folder name via the ``file = {…files/<NUM>/…}``
                   field in ``mineru/PDFs/PDFs.bib``.
      - citable:   True if citekey appears in ``bib_index`` (safe to cite).
    """
    exclude = exclude or set()
    bib_keys = set(bib_index) if bib_index else set()
    f2k = folder_to_bibkey()
    corpus: list[dict] = []
    for paper_dir in sorted(PARSED.iterdir()):
        if not paper_dir.is_dir():
            continue
        folder = paper_dir.name
        if folder in exclude:
            continue
        md_path = paper_dir / "auto" / f"{folder}.md"
        if not md_path.exists():
            continue
        # Resolve canonical Zotero key; fall back to folder name only when no mapping exists.
        citekey = f2k.get(folder, folder)
        citable = (not bib_index) or (citekey in bib_keys)
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        for i, chunk in enumerate(_chunk(text)):
            corpus.append({
                "citekey": citekey,
                "citable": citable,
                "chunk_id": f"{citekey}_c{i:03d}",
                "text": chunk,
            })
    return corpus


def bib_short_ref(meta: dict, citekey: str) -> str:
    """One-line human-readable reference for prompt context."""
    first_author = meta.get("author", "").split(",")[0].split(" and ")[0].strip()
    year = meta.get("year", "")
    title = meta.get("title", "")[:120]
    return f"[{citekey}] {first_author} ({year}). {title}"


# Pattern: ![](images/hash.jpg)  optionally followed by caption on next line
_IMG_RE = re.compile(
    r'!\[([^\]]*)\]\((images/[^\)]+)\)',
)
_FIG_CAPTION_RE = re.compile(
    r'!\[[^\]]*\]\(images/[^\)]+\)\s*\n(?P<cap>[^\n]{10,200})',
)


def load_figure_catalog(
    exclude: set[str] | None = None,
    bib_index: dict[str, dict] | None = None,
) -> list[dict]:
    """Return a catalog of every figure found in the OCR'd markdown files.

    Each entry::

        {
          "citekey":   "RN136",
          "citable":   True,
          "fig_path":  "/absolute/path/to/images/abc123.jpg",   # real file path
          "rel_path":  "images/abc123.jpg",                     # as in the markdown
          "caption":   "Figure 2. Neutron flux …",
          "context":   "surrounding paragraph text (up to 400 chars)",
        }

    Only entries where the image file actually exists on disk are included,
    so the writer can safely pass them to the render stage.
    """
    exclude = exclude or set()
    bib_keys = set(bib_index) if bib_index else set()
    f2k = folder_to_bibkey()
    catalog: list[dict] = []

    for paper_dir in sorted(PARSED.iterdir()):
        if not paper_dir.is_dir():
            continue
        folder = paper_dir.name
        if folder in exclude:
            continue
        md_path = paper_dir / "auto" / f"{folder}.md"
        if not md_path.exists():
            continue
        img_dir = paper_dir / "auto" / "images"
        citekey = f2k.get(folder, folder)
        citable = (not bib_index) or (citekey in bib_keys)
        text = md_path.read_text(encoding="utf-8", errors="ignore")

        # Walk line-by-line to capture caption (line after image tag)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = _IMG_RE.search(line)
            if not m:
                continue
            rel_path = m.group(2)            # e.g. "images/abc123.jpg"
            img_file = paper_dir / "auto" / rel_path
            if not img_file.exists():
                continue
            # Caption: next non-empty line if it looks like a figure caption
            caption = ""
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate and len(candidate) > 8:
                    caption = candidate
                    break
            # Context: paragraph around this line (up to 400 chars)
            start = max(0, i - 3)
            end   = min(len(lines), i + 5)
            context = " ".join(lines[start:end]).strip()[:400]

            catalog.append({
                "citekey":  citekey,
                "citable":  citable,
                "fig_path": str(img_file.resolve()),
                "rel_path": rel_path,
                "caption":  caption,
                "context":  context,
            })

    return catalog


if __name__ == "__main__":
    idx = load_bib_index()
    print(f"Bib entries: {len(idx)}")
    print(f"Sample: {list(idx.items())[0]}")
    corp = load_corpus(exclude={"05082026-Article-BNT Review-draft 2 clean"})
    print(f"\nCorpus chunks: {len(corp)} from "
          f"{len({c['citekey'] for c in corp})} papers")
    print(f"Sample chunk: {corp[0]['citekey']} → {corp[0]['text'][:200]}…")
    figs = load_figure_catalog(bib_index=idx)
    print(f"\nFigure catalog: {len(figs)} figures from "
          f"{len({f['citekey'] for f in figs})} papers")
    if figs:
        print(f"Sample: {figs[0]}")
