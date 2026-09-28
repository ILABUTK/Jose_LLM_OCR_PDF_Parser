"""Build an embedding visualization figure for slides.

Reads OCR'd markdowns from mineru/output_images/<ref>/auto/<ref>.md,
chunks them, computes TF-IDF + t-SNE projection, and saves a PNG
colored by inferred topic cluster.
"""
from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.manifold import TSNE
from sklearn.cluster import KMeans

REPO    = Path("/workspace") if Path("/workspace").exists() else Path(__file__).resolve().parent.parent
OCR_DIR = REPO / "mineru" / "output_images"
OUT_PNG = REPO / "slides" / "newfigures" / "embeddings.png"

# ── 1. Collect chunks ────────────────────────────────────────────────────────
def chunk_text(text: str, size: int = 600) -> list[str]:
    paras = re.split(r"\n\s*\n", text)
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) < size:
            buf += "\n\n" + p
        else:
            if buf.strip():
                chunks.append(buf.strip())
            buf = p
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if len(c) > 120]


chunks: list[str] = []
papers: list[str] = []
for md in sorted(OCR_DIR.glob("*/auto/*.md")):
    paper = md.parent.parent.name
    text = md.read_text(encoding="utf-8", errors="ignore")
    for c in chunk_text(text):
        chunks.append(c)
        papers.append(paper)

print(f"Collected {len(chunks)} chunks from {len(set(papers))} papers")

if len(chunks) < 20:
    raise SystemExit("Not enough chunks — run OCR first.")

# ── 2. TF-IDF → SVD → t-SNE ──────────────────────────────────────────────────
DOMAIN_STOPS = {
    "mathrm", "tag", "frac", "et", "al", "fig", "table", "ref", "eq",
    "jpg", "png", "images", "image", "doi", "https", "www", "com",
    "begin", "end", "cdot", "approx", "leq", "geq", "rangle", "langle",
    "alpha", "beta", "gamma", "delta", "sigma", "lambda", "mu",
    "et al", "al fig", "al table",
}
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
STOPS = list(ENGLISH_STOP_WORDS.union(DOMAIN_STOPS))

# Pre-clean: drop math-mode and image markdown
import re as _re
def clean(t: str) -> str:
    t = _re.sub(r"\$[^$]+\$", " ", t)
    t = _re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", t)
    t = _re.sub(r"\\[a-zA-Z]+\{[^}]*\}", " ", t)
    t = _re.sub(r"\\[a-zA-Z]+", " ", t)
    return t

clean_chunks = [clean(c) for c in chunks]

vec = TfidfVectorizer(max_features=4000, stop_words=STOPS,
                      ngram_range=(1, 2), min_df=3,
                      token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]{2,}\b")
X = vec.fit_transform(clean_chunks)
X_svd = TruncatedSVD(n_components=50, random_state=0).fit_transform(X)
X_2d  = TSNE(n_components=2, perplexity=min(30, len(chunks)//4),
             random_state=0, init="pca").fit_transform(X_svd)

# ── 3. Topic clusters ────────────────────────────────────────────────────────
N_CLUSTERS = 6
km = KMeans(n_clusters=N_CLUSTERS, random_state=0, n_init=10).fit(X_svd)
labels = km.labels_

# Top terms per cluster
terms = np.array(vec.get_feature_names_out())
centroids_text = vec.transform(chunks)
topic_names = []
for k in range(N_CLUSTERS):
    rows = (labels == k)
    if rows.sum() == 0:
        topic_names.append(f"topic {k}")
        continue
    mean_tfidf = np.asarray(centroids_text[rows].mean(axis=0)).ravel()
    top = terms[np.argsort(mean_tfidf)[::-1][:3]]
    topic_names.append(" / ".join(top))

# ── 4. Plot ──────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 6.2), dpi=140)
fig.patch.set_facecolor("white")

# Apple-ish palette
palette = ["#0071e3", "#34c759", "#ff9f0a", "#ff3b30",
           "#5856d6", "#af52de", "#00c7be", "#ff2d92"]

for k in range(N_CLUSTERS):
    m = labels == k
    ax.scatter(X_2d[m, 0], X_2d[m, 1],
               s=22, alpha=0.78, c=palette[k % len(palette)],
               edgecolors="white", linewidth=0.4,
               label=f"{topic_names[k]}")

# Per-paper centroids as small black dots
for paper in set(papers):
    pmask = np.array([p == paper for p in papers])
    cx, cy = X_2d[pmask].mean(axis=0)
    ax.scatter([cx], [cy], s=42, c="black", marker="o",
               edgecolors="white", linewidth=1.4, zorder=5)

ax.set_xticks([]); ax.set_yticks([])
for s in ("top", "right", "left", "bottom"):
    ax.spines[s].set_visible(False)

leg = ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.18),
                ncol=3, frameon=False, fontsize=9.5)

ax.set_title(f"{len(chunks)} chunks · {len(set(papers))} papers · "
             f"TF-IDF + t-SNE, k-means (k={N_CLUSTERS})",
             fontsize=10, color="#6e6e73", pad=10)

OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT_PNG, bbox_inches="tight", facecolor="white", dpi=160)
print(f"Saved: {OUT_PNG}")
