"""Force-directed + hierarchical graph: research questions from the structure
ontology.  Tree-map feel with controlled jitter; push-apart pass guarantees
no node overlap.  No baked-in title or legend — those live in the LaTeX slide.

Output: newfigures/research_directions.png
"""
import json, textwrap
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx

ROOT_DIR = Path(__file__).resolve().parents[1]
ONTO = ROOT_DIR / "paper_generation/ontologies/structure_ontology.json"
OUT  = Path(__file__).parent / "newfigures/research_directions.png"

ROLE_COLOR = {
    "abstract":    "#4C9BE8",
    "motivation":  "#E8A020",
    "background":  "#3CB878",
    "methods":     "#D966A8",
    "results":     "#E84040",
    "discussion":  "#F07030",
    "gaps":        "#8E44AD",
    "conclusion":  "#16A085",
    "backmatter":  "#95A5A6",
    "frontmatter": "#BDC3C7",
}

SHORT = {
    "Solid Breeder Ceramic Preparations":               "Preparations",
    "Irradiation Effects on Ceramic Materials":         "Irradiation\nEffects",
    "Advanced Ceramic Development for Fusion Reactors": "Advanced\nCeramics",
    "Tritium Recovery":                                 "T Recovery",
    "Gaps and Recommendations":                         "Gaps &\nRecs",
}

def shorten(s):
    for k, v in SHORT.items():
        s = s.replace(k, v)
    return s

def collect(tree):
    sections, roles, rqs_map, parent_of = [], {}, {}, {}
    def walk(node, parent=None):
        if isinstance(node, dict):
            t = node.get("title", "")
            r = node.get("role", "background")
            qs = node.get("research_questions_addressed", [])
            if t:
                sections.append(t)
                roles[t] = r
                rqs_map[t] = qs
                parent_of[t] = parent
            for c in node.get("children", []):
                walk(c, t)
        elif isinstance(node, list):
            for x in node:
                walk(x, parent)
    walk(tree)
    return sections, roles, rqs_map, parent_of

CORE_ROLES = {
    "abstract", "motivation", "background", "methods",
    "results", "discussion", "gaps", "conclusion",
}

# ── Tree-map layout with jitter ───────────────────────────────────────────────
def treemap_layout(sections, parent_of, rng, jitter=0.30):
    children_of = {s: [] for s in sections}
    roots = []
    for s in sections:
        p = parent_of.get(s)
        if p in sections:
            children_of[p].append(s)
        else:
            roots.append(s)

    def n_leaves(node):
        kids = children_of[node]
        return sum(n_leaves(k) for k in kids) if kids else 1

    pos = {}

    def place(nodes, x0, x1, y, depth=0):
        total = sum(n_leaves(n) for n in nodes)
        x_cur = x0
        y_step = 3.2  # vertical gap between levels
        for n in nodes:
            w = (x1 - x0) * n_leaves(n) / total
            cx = x_cur + w / 2 + rng.uniform(-jitter * w * 0.4, jitter * w * 0.4)
            cy = y         + rng.uniform(-jitter * 0.4, jitter * 0.4)
            pos[n] = (cx, cy)
            kids = children_of[n]
            if kids:
                place(kids, x_cur, x_cur + w, y - y_step)
            x_cur += w

    place(roots, -5.5, 5.5, 4.0)
    return pos

# ── Push-apart: prevent section node centers from being too close ─────────────
def push_apart(pos, nodes, min_dist, iterations=120):
    arr = {n: list(pos[n]) for n in nodes}
    for _ in range(iterations):
        for i, u in enumerate(nodes):
            for v in nodes[i + 1:]:
                dx = arr[v][0] - arr[u][0]
                dy = arr[v][1] - arr[u][1]
                d  = (dx**2 + dy**2) ** 0.5
                if d < min_dist and d > 1e-9:
                    push = (min_dist - d) / 2.0
                    nx_, ny_ = dx / d, dy / d
                    arr[u][0] -= push * nx_
                    arr[u][1] -= push * ny_
                    arr[v][0] += push * nx_
                    arr[v][1] += push * ny_
    for n in nodes:
        pos[n] = tuple(arr[n])

# ── RQ satellite placement around parent section ──────────────────────────────
def place_rqs(pos, sections, rqs_map, rng, r_base=3.2, r_jitter=0.6):
    all_rq_nodes = []
    for s in sections:
        sx, sy = pos[s]
        qs = rqs_map[s]
        n = len(qs)
        for j, q in enumerate(qs):
            angle = 2 * np.pi * j / max(n, 1) + rng.uniform(-0.25, 0.25)
            r = r_base + rng.uniform(0, r_jitter)
            pos[q] = (sx + r * np.cos(angle), sy + r * np.sin(angle))
            all_rq_nodes.append(q)
    return all_rq_nodes

def main():
    rng  = np.random.default_rng(7)
    data = json.load(open(ONTO))
    sections, roles, rqs_map, parent_of = collect(data["tree"])
    core_secs = [s for s in sections if roles[s] in CORE_ROLES]

    # ── Positions ────────────────────────────────────────────────────────────
    pos = treemap_layout(core_secs, parent_of, rng)
    push_apart(pos, core_secs, min_dist=3.0)        # section ↔ section
    all_rqs = place_rqs(pos, core_secs, rqs_map, rng)
    push_apart(pos, all_rqs, min_dist=2.4)          # RQ ↔ RQ
    # section ↔ RQ separation
    for s in core_secs:
        push_apart(pos, [s] + rqs_map[s], min_dist=2.6, iterations=80)
    # final global pass
    all_nodes = core_secs + all_rqs
    push_apart(pos, all_nodes, min_dist=2.0, iterations=80)

    # ── Build graph (edges only for drawing) ─────────────────────────────────
    G = nx.Graph()
    children_of = {s: [] for s in core_secs}
    for s in core_secs:
        p = parent_of.get(s)
        if p in core_secs:
            children_of[p].append(s)
            G.add_edge(s, p)
        for q in rqs_map[s]:
            G.add_edge(s, q)

    # ── Canvas ───────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(20, 15), dpi=150)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor("white")

    # ── Edges ────────────────────────────────────────────────────────────────
    for u, v in G.edges():
        x1, y1 = pos[u]
        x2, y2 = pos[v]
        is_hier = (u in core_secs and v in core_secs)
        ax.plot([x1, x2], [y1, y2],
                color="#444444" if is_hier else "#bbbbbb",
                lw=1.8 if is_hier else 0.9,
                alpha=0.70 if is_hier else 0.40,
                zorder=1)

    # ── RQ nodes — white box, colored border ─────────────────────────────────
    for s in core_secs:
        color = ROLE_COLOR.get(roles[s], "#cccccc")
        for q in rqs_map[s]:
            x, y = pos[q]
            wrapped = "\n".join(textwrap.wrap(q, width=26))
            ax.annotate(
                wrapped, xy=(x, y),
                fontsize=9.0, color="#1d1d1f",
                ha="center", va="center", zorder=3,
                bbox=dict(boxstyle="round,pad=0.40", fc="white",
                          ec=color, lw=1.8, alpha=0.95),
            )

    # ── Section nodes — colored fill, WHITE bold text ─────────────────────────
    for s in core_secs:
        x, y = pos[s]
        color = ROLE_COLOR.get(roles[s], "#cccccc")
        label = shorten(s)
        ax.annotate(
            label, xy=(x, y),
            fontsize=12.5, fontweight="bold", color="white",
            ha="center", va="center", zorder=5,
            bbox=dict(boxstyle="round,pad=0.55", fc=color,
                      ec="#222222", lw=2.2),
        )

    # ── Axis limits with generous padding ────────────────────────────────────
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    pad = 1.5
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)

    plt.tight_layout()
    OUT.parent.mkdir(exist_ok=True)
    plt.savefig(OUT, dpi=160, bbox_inches="tight", facecolor="white")
    n_rq = sum(len(rqs_map[s]) for s in core_secs)
    print(f"wrote {OUT}  ({len(core_secs)} sections, {n_rq} RQs)")

if __name__ == "__main__":
    main()

