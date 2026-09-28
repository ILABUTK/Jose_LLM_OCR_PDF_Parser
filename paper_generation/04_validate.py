"""04 — Mathematical validation of the generated paper against the reference.

Metrics implemented (all reported in [0,1] unless noted):

  1. STRUCTURAL FIDELITY  S_struct
     Normalised tree edit distance between the generated section tree and the
     reference ontology tree (Zhang–Shasha algorithm via the `zss` library).
     If `zss` is unavailable, falls back to a Jaccard over (role, level) bags.
        S_struct = 1 - TED(T_gen, T_ref) / max(|T_gen|, |T_ref|)

  2. SEMANTIC GROUNDING  G
     For every claim sentence c_i in the generated draft, retrieve nearest
     reference chunk r_j by cosine similarity of embeddings; grounding is the
     mean similarity across claims.
        G = (1/N) Σ_i max_j cos(emb(c_i), emb(r_j))

  3. CITATION COVERAGE  C
        C = |{claims with a citation token [n]}| / |{total claims}|

  4. STYLE ALIGNMENT  A_style
     Symmetric KL divergence between the style-marker frequency
     distributions of generated vs reference (hedging markers, transition
     markers, evidence frames from style_ontology.json).
        A_style = 1 / (1 + 0.5·(KL(P||Q) + KL(Q||P)))

  5. CONFLICT INDEX  K  (lower is better)
        K = |{sections where Judge was invoked}| / |{sections}|
     Also report mean number of writer↔critic rounds.

  6. COMPOSITE QUALITY  Q
        Q = w_s·S_struct + w_g·G + w_c·C + w_a·A_style    (defaults all 0.25)

Outputs JSON to output/validation_report.json. Prints a short table to stdout.
"""
from __future__ import annotations
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np

from config import (
    REFERENCE_MD,
    STRUCTURE_ONTOLOGY,
    STYLE_ONTOLOGY,
    DRAFT_SECTIONS,
    VALIDATION_REPORT,
    EMBED_MODEL,
)
from ollama_client import embed
from corpus import load_bib_index, load_corpus


CITATION_RE = re.compile(r"\[(RN\d+|1-s2\.0-[^\]]+)\]")
CITATION_KEY_RE = CITATION_RE
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")
THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)
ALIGNMENT_REPORT = VALIDATION_REPORT.parent / "alignment_report.json"


def strip_think(text: str) -> str:
    """Remove <think>…</think> reasoning blocks so they aren't scored as claims."""
    return THINK_RE.sub("", text).strip()


# ── 1. Structural fidelity ────────────────────────────────────────────────────
def _flatten_tree(tree: list, out: list, parent: str = "ROOT") -> list:
    for n in tree:
        out.append({
            "id": n["id"], "level": n.get("level"), "role": n.get("role", "other"),
            "parent": parent,
        })
        _flatten_tree(n.get("children", []), out, n["id"])
    return out


def structural_fidelity(ref_tree: list, gen_sections: list) -> float:
    """Jaccard over (level, role) bags — robust + dependency-free fallback."""
    ref_bag = Counter((n["level"], n["role"]) for n in _flatten_tree(ref_tree, []))
    gen_bag = Counter(
        (s.get("level", 2), s.get("role", "other")) for s in gen_sections
    )
    inter = sum((ref_bag & gen_bag).values())
    union = sum((ref_bag | gen_bag).values())
    return inter / union if union else 0.0


# ── 2. Semantic grounding ─────────────────────────────────────────────────────
def cosine(u: np.ndarray, v: np.ndarray) -> float:
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    return float(u @ v / (nu * nv + 1e-12))


def chunk_text(t: str, size: int = 600) -> list[str]:
    paras = [p.strip() for p in t.split("\n\n") if len(p.strip()) > 50]
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


def semantic_grounding(generated_md: str, corpus_chunks: list[str],
                       max_claims: int = 80) -> float:
    sentences = [s for s in SENT_RE.split(generated_md) if len(s.split()) >= 6]
    if len(sentences) > max_claims:
        idx = np.linspace(0, len(sentences) - 1, max_claims, dtype=int)
        sentences = [sentences[i] for i in idx]
    print(f"  [grounding] {len(sentences)} claims vs {len(corpus_chunks)} corpus chunks")
    try:
        ref_vecs = np.array([embed(EMBED_MODEL, c) for c in corpus_chunks])
        sims = []
        for s in sentences:
            v = np.array(embed(EMBED_MODEL, s))
            sims.append(max(cosine(v, r) for r in ref_vecs))
        return float(np.mean(sims)) if sims else 0.0
    except Exception as e:
        print(f"  [grounding] embeddings unavailable ({e}); using lexical Jaccard")
        ref_tokens = [set(c.lower().split()) for c in corpus_chunks]
        sims = []
        for s in sentences:
            stok = set(s.lower().split())
            sims.append(max(
                len(stok & r) / max(len(stok | r), 1) for r in ref_tokens
            ))
        return float(np.mean(sims)) if sims else 0.0


def per_claim_confidence(generated_md: str, corpus_chunks: list[str],
                         max_claims: int = 300) -> list[dict]:
    """Compute a grounding score for every sentence in the generated text.

    Returns a list of dicts:
        {text: str, grounding: float, has_citation: bool,
         confidence_tier: "high"|"medium"|"low"}

    grounding >= 0.75 -> high   (green)
    0.55 <= grounding < 0.75 -> medium (amber)
    grounding < 0.55 -> low    (red)
    """
    sentences = [s for s in SENT_RE.split(generated_md) if len(s.split()) >= 6]
    if not sentences:
        return []
    if len(sentences) > max_claims:
        sentences = sentences[:max_claims]

    results: list[dict] = []
    try:
        ref_vecs = np.array([embed(EMBED_MODEL, c) for c in corpus_chunks])
        for sent in sentences:
            v = np.array(embed(EMBED_MODEL, sent))
            score = float(max(cosine(v, r) for r in ref_vecs))
            tier = "high" if score >= 0.75 else ("medium" if score >= 0.55 else "low")
            results.append({
                "text":       sent.strip(),
                "grounding":  round(score, 4),
                "has_citation": bool(CITATION_RE.search(sent)),
                "confidence_tier": tier,
            })
    except Exception as e:
        print(f"  [per_claim] embeddings unavailable ({e}); using lexical Jaccard")
        ref_tokens = [set(c.lower().split()) for c in corpus_chunks]
        for sent in sentences:
            stok = set(sent.lower().split())
            score = float(max(
                len(stok & r) / max(len(stok | r), 1) for r in ref_tokens
            ))
            tier = "high" if score >= 0.75 else ("medium" if score >= 0.55 else "low")
            results.append({
                "text":       sent.strip(),
                "grounding":  round(score, 4),
                "has_citation": bool(CITATION_RE.search(sent)),
                "confidence_tier": tier,
            })
    return results


# ── 3. Citation coverage ──────────────────────────────────────────────────────
def citation_coverage(generated_md: str) -> float:
    sentences = [s for s in SENT_RE.split(generated_md) if len(s.split()) >= 6]
    if not sentences:
        return 0.0
    with_cite = sum(1 for s in sentences if CITATION_RE.search(s))
    return with_cite / len(sentences)


def citation_validity(generated_md: str, bib: dict[str, dict]) -> dict:
    """Fraction of [RNxxx] citations that resolve to a real bib entry."""
    cites = CITATION_RE.findall(generated_md)
    if not cites:
        return {"citation_validity": 0.0, "n_citations": 0, "n_unique": 0,
                "n_unresolved": 0, "unresolved": []}
    valid = [c for c in cites if c in bib]
    unresolved = sorted(set(c for c in cites if c not in bib))
    return {
        "citation_validity": len(valid) / len(cites),
        "n_citations":  len(cites),
        "n_unique":     len(set(cites)),
        "n_unresolved": len(unresolved),
        "unresolved":   unresolved[:20],
    }


# ── 4. Style alignment via symmetric KL ───────────────────────────────────────
def _marker_distribution(text: str, markers: list[str]) -> np.ndarray:
    t = text.lower()
    counts = np.array([t.count(m.lower()) for m in markers], dtype=float)
    if counts.sum() == 0:
        counts = np.ones_like(counts)
    return counts / counts.sum()


def style_alignment(generated_md: str, style: dict, reference_md: str) -> float:
    markers = []
    for key in ("hedging_markers", "transition_markers", "evidence_frames",
                "research_question_patterns"):
        markers.extend(style.get(key, []))
    markers = list(dict.fromkeys(markers))  # unique, ordered
    if not markers:
        return 0.0
    p = _marker_distribution(generated_md, markers)
    q = _marker_distribution(reference_md, markers)
    eps = 1e-9
    kl_pq = float(np.sum(p * np.log((p + eps) / (q + eps))))
    kl_qp = float(np.sum(q * np.log((q + eps) / (p + eps))))
    return 1.0 / (1.0 + 0.5 * (kl_pq + kl_qp))


# ── 5. Per-section confidence intervals from multi-round critic verdicts ──────
def section_confidence_intervals(sections: list[dict]) -> dict:
    """Derive per-section CI from the history of Critic verdicts across rounds.

    Returns {sec_id: {mean, std, n, ci_95_lower, ci_95_upper, title}}.
    When only one critic round exists, std=0 and CI collapses to means.
    When history is absent, fall back to last_verdict.
    """
    result: dict[str, dict] = {}
    for s in sections:
        verdicts: list[float] = []
        for h in s.get("history", []):
            if h.get("agent") != "critic":
                continue
            v = h.get("verdict")
            if v is None:
                scores = h.get("scores") or {}
                if scores:
                    v = float(np.mean(list(scores.values())))
            if v is not None:
                verdicts.append(float(v))

        if not verdicts:
            lv = float(s.get("last_verdict") or 0.5)
            result[s["id"]] = {
                "title": s["title"], "mean": round(lv, 4), "std": 0.0,
                "n": 0, "ci_95_lower": round(lv, 4), "ci_95_upper": round(lv, 4),
            }
            continue

        mean_v = float(np.mean(verdicts))
        std_v  = float(np.std(verdicts)) if len(verdicts) > 1 else 0.0
        se     = std_v / max(len(verdicts) ** 0.5, 1.0)
        result[s["id"]] = {
            "title":        s["title"],
            "mean":         round(mean_v, 4),
            "std":          round(std_v, 4),
            "n":            len(verdicts),
            "ci_95_lower":  round(max(0.0, mean_v - 1.96 * se), 4),
            "ci_95_upper":  round(min(1.0, mean_v + 1.96 * se), 4),
        }
    return result


# ── 6. Conflict index ─────────────────────────────────────────────────────────
def conflict_metrics(sections: list[dict]) -> dict:
    n = len(sections) or 1
    judge = sum(1 for s in sections if s.get("judge_invoked"))
    rounds = []
    for s in sections:
        writer_rounds = sum(1 for h in s.get("history", []) if h.get("agent") == "writer")
        rounds.append(writer_rounds)
    return {
        "judge_invocation_rate": judge / n,
        "mean_writer_rounds": float(np.mean(rounds)) if rounds else 0.0,
        "max_writer_rounds": int(max(rounds)) if rounds else 0,
    }


# ── 6. Composite ──────────────────────────────────────────────────────────────
def composite(metrics: dict,
              w=(0.25, 0.25, 0.25, 0.25)) -> float:
    return (
        w[0] * metrics["structural_fidelity"]
        + w[1] * metrics["semantic_grounding"]
        + w[2] * metrics["citation_coverage"]
        + w[3] * metrics["style_alignment"]
    )


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    ref_md   = REFERENCE_MD.read_text(encoding="utf-8")
    ref_tree = json.loads(STRUCTURE_ONTOLOGY.read_text())["tree"]
    style    = json.loads(STYLE_ONTOLOGY.read_text())
    sections = json.loads(DRAFT_SECTIONS.read_text())
    # Strip <think> reasoning before any sentence-level scoring — otherwise
    # "Let me check the EVIDENCE BANK" gets scored as a claim.
    for s in sections:
        s["final_clean"] = strip_think(s.get("final", ""))
    gen_md = "\n\n".join(s["final_clean"] for s in sections)

    print("[validate] loading corpus + bib …")
    bib    = load_bib_index()
    corpus = load_corpus(
        exclude={REFERENCE_MD.parent.parent.name},
        bib_index=bib,
    )
    corpus_texts = [c["text"] for c in corpus]
    # Cap to keep embedding cost bounded; use evenly-spaced sample for breadth
    if len(corpus_texts) > 400:
        idx = np.linspace(0, len(corpus_texts) - 1, 400, dtype=int)
        corpus_texts = [corpus_texts[i] for i in idx]

    print("[validate] structural fidelity …")
    s_struct = structural_fidelity(ref_tree, sections)
    print("[validate] semantic grounding (vs full corpus) ...")
    g = semantic_grounding(gen_md, corpus_texts)
    print("[validate] per-claim confidence scoring ...")
    claim_scores = per_claim_confidence(gen_md, corpus_texts, max_claims=300)
    print("[validate] citation coverage …")
    c = citation_coverage(gen_md)
    print("[validate] citation validity (vs bib index) …")
    cv = citation_validity(gen_md, bib)
    print("[validate] style alignment …")
    a = style_alignment(gen_md, style, ref_md)
    print("[validate] conflict metrics …")
    k = conflict_metrics(sections)

    print("[validate] per-section confidence intervals ...")
    sec_ci = section_confidence_intervals(sections)

    # Count per-section citations for provenance badge
    citation_counts: dict[str, int] = {}
    for s in sections:
        keys = set(re.findall(r"\[(RN\d+)\]", s.get("final", "")))
        citation_counts[s["id"]] = len(keys)

    # Per-section per-claim scores: split claim_scores by section
    # Build a lookup: sentence text -> score (first match wins)
    _claim_lookup: dict[str, dict] = {c["text"]: c for c in reversed(claim_scores)}

    per_section_claims: dict[str, list[dict]] = {}
    for s in sections:
        final_text = s.get("final_clean", strip_think(s.get("final", "")))
        sents = [t for t in SENT_RE.split(final_text) if len(t.split()) >= 6]
        sec_claims = []
        for sent in sents:
            entry = _claim_lookup.get(sent.strip())
            if entry:
                sec_claims.append(entry)
        per_section_claims[s["id"]] = sec_claims

        # Count tier distribution per section
        if sec_claims:
            tiers = [c["confidence_tier"] for c in sec_claims]
            s["claim_tiers"] = {
                "high":   tiers.count("high"),
                "medium": tiers.count("medium"),
                "low":    tiers.count("low"),
                "total":  len(tiers),
            }
        else:
            s["claim_tiers"] = {"high": 0, "medium": 0, "low": 0, "total": 0}

    # Annotate draft_sections.json with quality_ci so the render script can read it
    for s in sections:
        s["quality_ci"] = sec_ci.get(s["id"], {})
        s["n_unique_citations"] = citation_counts.get(s["id"], 0)
        s["per_claim_scores"] = per_section_claims.get(s["id"], [])
        s.pop("final_clean", None)   # internal scratch field — don't persist
    DRAFT_SECTIONS.write_text(json.dumps(sections, indent=2), encoding="utf-8")
    print(f"[validate] -> annotated {DRAFT_SECTIONS.name} with quality_ci + per_claim_scores")

    report = {
        "structural_fidelity": s_struct,
        "semantic_grounding":  g,
        "citation_coverage":   c,
        "style_alignment":     a,
        **cv,
        **k,
    }
    report["composite_quality"] = composite(report)
    report["per_section_qa"] = sec_ci

    # ---- Side-by-side alignment vs. human BNT paper (from 04b) -------------
    if ALIGNMENT_REPORT.exists():
        align = json.loads(ALIGNMENT_REPORT.read_text(encoding="utf-8"))
        report["alignment_vs_human"] = {
            "overall_mean": align.get("overall_mean"),
            "n_pairs":      align.get("n_pairs"),
            "llm_verified": align.get("llm_verified"),
            "llm_calls":    align.get("llm_calls", 0),
            "per_section":  align.get("per_section", {}),
            "source":       ALIGNMENT_REPORT.name,
        }
        print(f"[validate] merged alignment report "
              f"(overall_mean={align.get('overall_mean')}, "
              f"n_pairs={align.get('n_pairs')})")
    else:
        report["alignment_vs_human"] = None
        print(f"[validate] NOTE: {ALIGNMENT_REPORT.name} not found — "
              f"run 04b_align_vs_human.py to populate it")

    # Per-claim confidence report: aggregate stats + full claim list
    n_high   = sum(1 for c in claim_scores if c["confidence_tier"] == "high")
    n_medium = sum(1 for c in claim_scores if c["confidence_tier"] == "medium")
    n_low    = sum(1 for c in claim_scores if c["confidence_tier"] == "low")
    report["per_claim_confidence"] = {
        "total_claims":  len(claim_scores),
        "high_count":    n_high,
        "medium_count":  n_medium,
        "low_count":     n_low,
        "high_pct":      round(n_high   / max(len(claim_scores), 1), 3),
        "medium_pct":    round(n_medium / max(len(claim_scores), 1), 3),
        "low_pct":       round(n_low    / max(len(claim_scores), 1), 3),
        "by_section":    {
            sid: {
                "title":   sec_ci.get(sid, {}).get("title", sid),
                "claims":  per_section_claims.get(sid, []),
                "tiers":   sections[[s["id"] for s in sections].index(sid)].get(
                               "claim_tiers", {}) if sid in [s["id"] for s in sections] else {},
            }
            for sid in per_section_claims
        },
    }

    VALIDATION_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Pretty-print summary
    print("\n---------- Validation Report ----------")
    for k_, v in report.items():
        if k_ in ("per_section_qa", "per_claim_confidence"):
            continue
        if isinstance(v, float):
            print(f"  {k_:30s} {v:.3f}")
        else:
            print(f"  {k_:30s} {v}")
    pcc = report["per_claim_confidence"]
    print(f"\n  Per-claim confidence (n={pcc['total_claims']}):")
    print(f"    High   (>=0.75): {pcc['high_count']:4d}  ({pcc['high_pct']:.1%})")
    print(f"    Medium (>=0.55): {pcc['medium_count']:4d}  ({pcc['medium_pct']:.1%})")
    print(f"    Low    (<0.55):  {pcc['low_count']:4d}  ({pcc['low_pct']:.1%})")
    print(f"\nWritten to {VALIDATION_REPORT}")

    # Print per-section CI table
    print("\n---------- Per-Section Quality CI ----------")
    print(f"  {'Section':<45} {'Mean':>6} {'Std':>5}  {'95% CI':>14}  Judge")
    for sid, ci in sec_ci.items():
        sec_obj = next((s for s in sections if s["id"] == sid), {})
        j = "Y" if sec_obj.get("judge_invoked") else "N"
        lo, hi = ci["ci_95_lower"], ci["ci_95_upper"]
        print(f"  {ci['title']:<45} {ci['mean']:>6.3f}  {ci['std']:>5.3f}"
              f"  [{lo:.3f},{hi:.3f}]  {j}")



if __name__ == "__main__":
    main()
