"""Corpus loader for the restructured pipeline.

Starting point is a *single mounted folder* containing:
  - pdfs/            the source papers (PDF)
  - *.bib            BibTeX references, OR
  - *.enw / *.ris    EndNote / RIS references

This module:
  1. parses the reference file(s) into {citekey: metadata}
  2. extracts full text + embedded images from every PDF
  3. chunks the text into paragraph-sized evidence units
  4. provides a lightweight TF-IDF retriever (no external services)

It deliberately has NO dependency on mineru / zotero / crawl4ai / searxng.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import config

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - pypdf is a hard dep, guard for import order
    PdfReader = None  # type: ignore


# ── Reference parsing ────────────────────────────────────────────────────────
_BIB_ENTRY = re.compile(r"@\w+\s*\{\s*(?P<key>[^,\s]+)\s*,(?P<body>.*?)\n\}", re.DOTALL)
_BIB_FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.+?)[}\"]\s*,?\s*$", re.MULTILINE | re.DOTALL)


def _parse_bib(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in _BIB_ENTRY.finditer(text):
        key = m.group("key").strip()
        fields = {f.group(1).lower(): f.group(2).strip()
                  for f in _BIB_FIELD.finditer(m.group("body") + "\n")}
        out[key] = {
            "title": fields.get("title", ""),
            "author": fields.get("author", ""),
            "year": fields.get("year", ""),
            "doi": fields.get("doi", ""),
            "journal": fields.get("journal", fields.get("booktitle", "")),
            "abstract": fields.get("abstract", ""),
        }
    return out


# RIS / EndNote tag map
_RIS_MAP = {
    "TI": "title", "T1": "title",
    "AU": "author", "A1": "author",
    "PY": "year", "Y1": "year",
    "DO": "doi",
    "JO": "journal", "JF": "journal", "T2": "journal",
    "AB": "abstract", "N2": "abstract",
}


def _parse_ris(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cur: dict = {}
    authors: list[str] = []
    idx = 0
    for line in text.splitlines():
        m = re.match(r"^([A-Z0-9]{2})\s+-\s*(.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = {}
            authors = []
        elif tag == "ER":
            if authors:
                cur["author"] = " and ".join(authors)
            idx += 1
            key = cur.get("_key") or f"ref{idx}"
            cur.pop("_key", None)
            out[key] = {
                "title": cur.get("title", ""),
                "author": cur.get("author", ""),
                "year": cur.get("year", "")[:4],
                "doi": cur.get("doi", ""),
                "journal": cur.get("journal", ""),
                "abstract": cur.get("abstract", ""),
            }
        elif tag in ("AU", "A1"):
            authors.append(val)
        elif tag == "ID":
            cur["_key"] = val
        elif tag in _RIS_MAP:
            cur[_RIS_MAP[tag]] = val
    return out


def load_bib_index() -> dict[str, dict]:
    """Merge every .bib / .enw / .ris file found directly in the input dir."""
    index: dict[str, dict] = {}
    for f in sorted(config.INPUT_DIR.glob("*")):
        if f.suffix.lower() == ".bib":
            index.update(_parse_bib(f.read_text(encoding="utf-8", errors="ignore")))
        elif f.suffix.lower() in (".enw", ".ris"):
            index.update(_parse_ris(f.read_text(encoding="utf-8", errors="ignore")))
    return index


# ── PDF extraction ───────────────────────────────────────────────────────────
def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _extract_pdf(path: Path, image_out: Path) -> tuple[str, list[str]]:
    """Return (full_text, [saved_image_paths]) for one PDF."""
    if PdfReader is None:
        return "", []
    text_parts: list[str] = []
    images: list[str] = []
    try:
        reader = PdfReader(str(path))
    except Exception as e:  # corrupt / encrypted
        print(f"  [corpus] cannot read {path.name}: {e}")
        return "", []
    for pno, page in enumerate(reader.pages):
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            pass
        # Pull embedded raster images so graph nodes can reference a paper's
        # OWN figures when prompting ComfyUI.
        try:
            for ino, img in enumerate(getattr(page, "images", [])):
                dst = image_out / f"{_slug(path.stem)}_p{pno}_{ino}{Path(img.name).suffix or '.png'}"
                dst.write_bytes(img.data)
                images.append(str(dst))
        except Exception:
            pass
    return "\n".join(text_parts), images


def _chunk(text: str, size: int = 700) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 80]
    chunks: list[str] = []
    buf = ""
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


# ── Retriever ────────────────────────────────────────────────────────────────
_WORD = re.compile(r"[a-z0-9]+")


def _tok(s: str) -> list[str]:
    return _WORD.findall(s.lower())


@dataclass
class Corpus:
    bib: dict[str, dict]
    chunks: list[dict] = field(default_factory=list)        # {citekey, chunk_id, text}
    figures: list[dict] = field(default_factory=list)       # {citekey, path}
    _idf: dict[str, float] = field(default_factory=dict)
    _vecs: list[Counter] = field(default_factory=list)

    # retrieval -------------------------------------------------------------
    def _build_index(self) -> None:
        df: Counter = Counter()
        docs: list[Counter] = []
        for c in self.chunks:
            tf = Counter(_tok(c["text"]))
            docs.append(tf)
            for term in tf:
                df[term] += 1
        n = max(len(docs), 1)
        self._idf = {t: math.log(1 + n / (1 + d)) for t, d in df.items()}
        self._vecs = docs

    def search(self, query: str, k: int = 6) -> list[dict]:
        if not self._vecs:
            self._build_index()
        q = Counter(_tok(query))
        qv = {t: f * self._idf.get(t, 0.0) for t, f in q.items()}
        qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
        scored: list[tuple[float, int]] = []
        for i, dv in enumerate(self._vecs):
            num = sum(qv.get(t, 0.0) * f * self._idf.get(t, 0.0) for t, f in dv.items())
            dn = math.sqrt(sum((f * self._idf.get(t, 0.0)) ** 2 for t, f in dv.items())) or 1.0
            scored.append((num / (qn * dn), i))
        scored.sort(reverse=True)
        out = []
        for score, i in scored[:k]:
            c = dict(self.chunks[i])
            c["score"] = round(score, 4)
            out.append(c)
        return out

    def figures_for(self, citekey: str) -> list[dict]:
        return [f for f in self.figures if f["citekey"] == citekey]

    def short_ref(self, citekey: str) -> str:
        m = self.bib.get(citekey, {})
        author = m.get("author", "").split(",")[0].split(" and ")[0].strip()
        return f"[{citekey}] {author} ({m.get('year','')}). {m.get('title','')[:120]}"


def _match_citekey(pdf_stem: str, bib: dict[str, dict]) -> str:
    """Best-effort map a PDF filename to a bib citekey by fuzzy title overlap."""
    toks = set(_tok(pdf_stem))
    best, best_key = 0.0, _slug(pdf_stem)
    for key, meta in bib.items():
        overlap = len(toks & set(_tok(meta.get("title", "")))) + (3 if key.lower() in pdf_stem.lower() else 0)
        if overlap > best:
            best, best_key = overlap, key
    return best_key


def load_corpus() -> Corpus:
    bib = load_bib_index()
    corpus = Corpus(bib=bib)
    img_dir = config.OUTPUT_DIR / "corpus_images"
    img_dir.mkdir(parents=True, exist_ok=True)
    if not config.PDF_DIR.exists():
        print(f"  [corpus] no pdfs/ folder at {config.PDF_DIR}")
        return corpus
    for pdf in sorted(config.PDF_DIR.rglob("*.pdf")):
        citekey = _match_citekey(pdf.stem, bib) if bib else _slug(pdf.stem)
        text, images = _extract_pdf(pdf, img_dir)
        for i, ch in enumerate(_chunk(text)):
            corpus.chunks.append({
                "citekey": citekey,
                "chunk_id": f"{citekey}_c{i:03d}",
                "text": ch,
            })
        for img in images:
            corpus.figures.append({"citekey": citekey, "path": img})
    corpus._build_index()
    print(f"  [corpus] {len(corpus.chunks)} chunks / {len(corpus.figures)} figures "
          f"from {len(set(c['citekey'] for c in corpus.chunks))} papers")
    return corpus


if __name__ == "__main__":
    c = load_corpus()
    print("bib entries:", len(c.bib))
    for hit in c.search("tritium release temperature", k=3):
        print(f"  {hit['score']:.3f}  {hit['chunk_id']}")
