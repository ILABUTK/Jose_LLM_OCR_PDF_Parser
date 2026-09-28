"""04b — Sentence-level alignment of the generated paper vs. the human BNT review.

For every claim sentence c_i in the generated draft:
  1.  Strip <think>…</think>, then split into sentences.
  2.  Find the top-k nearest human sentences by embedding cosine (similarity s_i).
  3.  Optionally ask the LLM "do these claim the same thing?" (verdict v_i ∈ {0,1}
      with a 0–1 confidence) — gated by --llm; without it v_i is None.
  4.  Final per-pair score   p_i = s_i   if v_i is None
                              p_i = 0.5·s_i + 0.5·v_i  otherwise.
  5.  Per-section score = mean(p_i over its claims);
      overall alignment score = mean(p_i over all claims).

Outputs JSON to  output/alignment_report.json :
    {
      "overall_mean": float,
      "n_pairs": int,
      "llm_verified": bool,
      "per_section": {sec_id: {title, mean, n}},
      "pairs": [ {sec_id, section_title, gen, human, sim, llm, final}, … ]
    }

Usage:
    python -u 04b_align_vs_human.py                # similarity only (fast, CPU/GPU embedding)
    python -u 04b_align_vs_human.py --llm          # also LLM-verify each pair (slow)
    python -u 04b_align_vs_human.py --max-claims 6 # cap pairs per section
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

import numpy as np

from config import (
    REFERENCE_MD,
    DRAFT_SECTIONS,
    OUTPUT_DIR,
    EMBED_MODEL,
    PLANNER_MODEL,
)
from ollama_client import embed, chat_json

ALIGN_REPORT = OUTPUT_DIR / "alignment_report.json"

THINK_RE     = re.compile(r"<think>.*?</think>", flags=re.DOTALL)
SENT_SPLIT   = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[\$])")
CITATION_RE  = re.compile(r"\[(RN\d+|1-s2\.0-[^\]]+)\]|\\cite\{[^}]+\}")
CODEFENCE_RE = re.compile(r"```.*?```", flags=re.DOTALL)
HEADING_RE   = re.compile(r"^\s*#+\s.*$", flags=re.MULTILINE)
TABLE_RE     = re.compile(r"^\s*\|.*\|\s*$", flags=re.MULTILINE)


# ── Reference loader ──────────────────────────────────────────────────────────
def load_reference(path: Path) -> str:
    """Load the human BNT markdown; fall back to bk.output_images if missing."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    alt = Path(str(path).replace("output_images", "bk.output_images", 1))
    if alt.exists():
        print(f"  [ref] using fallback path: {alt}")
        return alt.read_text(encoding="utf-8")
    raise FileNotFoundError(f"reference markdown not found at {path} or {alt}")


def split_sentences(text: str, min_words: int = 6) -> list[str]:
    """Strip <think>, code fences, headings and table rows, then sentence-split."""
    text = THINK_RE.sub("", text)
    text = CODEFENCE_RE.sub("", text)
    text = HEADING_RE.sub("", text)
    text = TABLE_RE.sub("", text)
    sents = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        for s in SENT_SPLIT.split(para):
            s = s.strip().lstrip("-*•").strip()
            if (len(s.split()) >= min_words
                    and not s.startswith("|")
                    and not s.startswith("![")):
                sents.append(s)
    return sents


# ── Similarity helpers ────────────────────────────────────────────────────────
def cosine(u: np.ndarray, v: np.ndarray) -> float:
    n = (np.linalg.norm(u) * np.linalg.norm(v)) or 1.0
    return float(np.dot(u, v) / n)


def embed_many(model: str, texts: list[str]) -> np.ndarray:
    """Embed a list of strings; falls back to a lexical bag-of-words vector
    if the embedding server is unreachable, so the script always runs."""
    try:
        vecs = [embed(model, t) for t in texts]
        return np.asarray(vecs, dtype=np.float32)
    except Exception as e:
        print(f"  [embed] embedding server unavailable ({e}); using TF bag-of-words")
        vocab: dict[str, int] = {}
        for t in texts:
            for w in re.findall(r"[a-z]{3,}", t.lower()):
                vocab.setdefault(w, len(vocab))
        M = np.zeros((len(texts), len(vocab) or 1), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z]{3,}", t.lower()):
                M[i, vocab[w]] += 1.0
        return M


# ── Optional LLM equivalence check ────────────────────────────────────────────
LLM_PROMPT = (
    "You are a strict scientific reviewer comparing two sentences.\n"
    "Decide whether they make the SAME factual claim about the same material, "
    "property, or process. Numeric values may differ by up to ~20%.\n\n"
    "Reply ONLY in compact JSON with EXACTLY these keys:\n"
    '  {"equivalent": 0 or 1,\n'
    '   "confidence": 0.0 to 1.0,\n'
    '   "agreement": "<short summary of what BOTH sentences agree on, '
    'or empty if equivalent=0>",\n'
    '   "differences": "<specific, concrete differences in claim, value, '
    'material, condition, or scope — 1 sentence>"}\n\n'
    "equivalent=1 only when the claims overlap on subject AND property; "
    "otherwise equivalent=0 and explain the gap in `differences`."
)


def llm_verify(gen: str, human: str, model: str) -> dict | None:
    msg = [
        {"role": "system", "content": LLM_PROMPT},
        {"role": "user",
         "content": f"GENERATED: {gen}\nHUMAN:     {human}"},
    ]
    try:
        out = chat_json(model, msg, options={"temperature": 0.0,
                                             "num_predict": 220})
        eq = int(bool(out.get("equivalent", 0)))
        conf = float(out.get("confidence", 0.0))
        return {
            "equivalent":  eq,
            "confidence":  conf,
            "agreement":   str(out.get("agreement",   ""))[:300],
            "differences": str(out.get("differences", ""))[:300],
        }
    except Exception as e:
        return {"equivalent": None, "confidence": None,
                "agreement": "", "differences": f"err:{e}"}


# ── Driver ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true",
                    help="LLM-verify every aligned pair (slow)")
    ap.add_argument("--max-claims", type=int, default=10,
                    help="max generated claims to align per section")
    ap.add_argument("--llm-budget", type=int, default=0,
                    help="cap on number of LLM verifications "
                         "(0 = no cap, verify ALL pairs)")
    args = ap.parse_args()

    # 1.  Load + split reference + draft ---------------------------------------
    ref_md = load_reference(REFERENCE_MD)
    human_sents = split_sentences(ref_md, min_words=8)
    print(f"[load] human sentences:     {len(human_sents)}")

    drafts = json.loads(Path(DRAFT_SECTIONS).read_text(encoding="utf-8"))
    print(f"[load] generated sections:  {len(drafts)}")

    # 2.  Embed the human corpus once -----------------------------------------
    print("[embed] human reference …")
    H = embed_many(EMBED_MODEL, human_sents)

    # 3.  Per-section alignment ------------------------------------------------
    pairs = []
    per_section = {}
    llm_calls = 0
    for sec in drafts:
        sents = split_sentences(sec.get("final", ""), min_words=8)
        if not sents:
            continue
        # Prefer sentences with a numeric value or a citation — those are claims
        scored = sorted(
            sents,
            key=lambda s: (bool(re.search(r"\d", s))
                           + bool(CITATION_RE.search(s))),
            reverse=True,
        )
        cands = scored[: args.max_claims]
        if not cands:
            continue

        print(f"[align] {sec['id']:8} {sec['title'][:48]:50} "
              f"({len(cands)} claims)")
        G = embed_many(EMBED_MODEL, cands)
        # pad to equal dim (TF fallback)
        if G.shape[1] != H.shape[1]:
            # different vocabs from fallback → recompute together
            combined = cands + human_sents
            M = embed_many(EMBED_MODEL, combined)
            G, H_local = M[: len(cands)], M[len(cands):]
        else:
            H_local = H

        # Cosine matrix
        Gn = G / (np.linalg.norm(G, axis=1, keepdims=True) + 1e-9)
        Hn = H_local / (np.linalg.norm(H_local, axis=1, keepdims=True) + 1e-9)
        sim = Gn @ Hn.T                              # (n_gen, n_human)

        sec_scores = []
        for i, g_sent in enumerate(cands):
            j = int(sim[i].argmax())
            s = float(sim[i, j])
            verdict = None
            budget_left = (args.llm_budget == 0
                           or llm_calls < args.llm_budget)
            if args.llm and budget_left:
                verdict = llm_verify(g_sent, human_sents[j], PLANNER_MODEL)
                llm_calls += 1
                # final blends similarity + LLM confidence (signed by equivalent)
                if verdict and verdict["equivalent"] is not None:
                    v = verdict["confidence"] if verdict["equivalent"] else 0.0
                    final = 0.5 * s + 0.5 * v
                else:
                    final = s
            else:
                final = s
            sec_scores.append(final)
            pairs.append({
                "sec_id":        sec["id"],
                "section_title": sec["title"],
                "gen":           g_sent,
                "human":         human_sents[j],
                "sim":           round(s, 4),
                "llm":           verdict,
                "final":         round(float(final), 4),
            })
        per_section[sec["id"]] = {
            "title": sec["title"],
            "mean":  round(float(np.mean(sec_scores)), 4),
            "n":     len(sec_scores),
        }

    overall = float(np.mean([p["final"] for p in pairs])) if pairs else 0.0
    report = {
        "overall_mean":  round(overall, 4),
        "n_pairs":       len(pairs),
        "llm_verified":  bool(args.llm),
        "llm_calls":     llm_calls,
        "per_section":   per_section,
        "pairs":         pairs,
    }
    ALIGN_REPORT.parent.mkdir(parents=True, exist_ok=True)
    ALIGN_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                            encoding="utf-8")

    # ── Summary --------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"  Overall alignment mean : {overall:.3f}")
    print(f"  Pairs                   : {len(pairs)}")
    print(f"  LLM-verified            : {args.llm} ({llm_calls} calls)")
    print("=" * 60)
    print(f"{'sec_id':10}{'mean':>8}{'n':>5}  title")
    for sid, v in per_section.items():
        print(f"{sid:10}{v['mean']:>8.3f}{v['n']:>5}  {v['title'][:55]}")
    print(f"\n[done] wrote {ALIGN_REPORT}")


if __name__ == "__main__":
    main()
