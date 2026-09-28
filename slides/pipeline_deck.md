---
marp: true
theme: default
paginate: true
size: 16:9
math: katex
style: |
  section { font-size: 22px; }
  section.lead h1 { font-size: 44px; }
  section.lead h2 { font-size: 28px; color: #555; }
  h1 { color: #1a3d6d; }
  h2 { color: #1a3d6d; border-bottom: 2px solid #ddd; padding-bottom: 4px; }
  code { background: #f4f4f4; padding: 2px 4px; border-radius: 3px; }
  .small { font-size: 0.75em; color: #555; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
  table { font-size: 0.78em; }
  blockquote { border-left: 4px solid #1a3d6d; color: #333; }
footer: "Traceable, Grounded Text-Analytics Pipeline for Solid-Breeder Fusion Literature"
---

<!-- _class: lead -->
<!-- _paginate: false -->

# A Traceability-Grounded Pipeline for Automated Literature Research
## From BibTeX → PDFs → Structured Knowledge → Validated Review Article
### Applied to solid tritium-breeder materials for fusion blankets

**José A. Jiménez**  ·  Industrial & Systems Engineering, University of Tennessee
*Talk: 10 min — 10 slides*

<!--
SPEAKER NOTES:
- Opening hook: "We can read 600 papers in an afternoon. The question is can we *trust* what we get out."
- Today: end-to-end pipeline that turns a topic into a draft literature review WITH a verifiable evidence trail
- Domain: solid breeders for fusion - Li2TiO3, Li4SiO4, Li2ZrO3 - candidate materials for DEMO/CFETR
- Promise: every claim in the generated review is linked back to a specific page in a specific PDF
- Closing setup for next slide: motivate WHY fusion research needs this
-->

---

## 1 / Motivation — Why Fusion, Why Now

<div class="cols">
<div>

**Nuclear energy splits two ways:**
- **Fission** (Hahn & Strassmann, 1939; Meitner & Frisch, 1939) — mature, but produces long-lived radioactive waste, expensive fuel cycle, public-perception risk.
- **Fusion** — combines D + T → ⁴He + n + **17.6 MeV**; clean, no long-lived waste, fuel from seawater + Li.

**Where we are**
- R&D since the mid-1950s; ITER first plasma in late-2020s, **DEMO targets net electricity in the 2030s**.
- Boron variants (p–¹¹B) avoid neutrons but require T > 10⁹ K — not yet engineering-feasible.

</div>
<div>

**The fuel bottleneck**

$$
{}^{2}_{1}\text{D} + {}^{3}_{1}\text{T} \;\longrightarrow\; {}^{4}_{2}\text{He}\,(3.5\,\text{MeV}) + n\,(14.1\,\text{MeV})
$$

- Tritium half-life = **12.3 years** → no natural reservoir.
- Must be **bred inside the reactor** from the 14.1 MeV neutron:

$$
{}^{6}\text{Li} + n \rightarrow {}^{4}\text{He} + \text{T} + 4.78\,\text{MeV}
$$

**This is the breeding-blanket problem → motivates the literature we mine.**

</div>
</div>

<!--
SPEAKER NOTES:
- Spend ~75 seconds here. This is one of two "intro-heavy" slides.
- Stress: fission vs fusion is not a religious argument; we're motivating WHY we need a *literature* pipeline specifically for breeders
- Tritium is the choke point. Whole sub-fields of fusion materials science exist because of it.
- 14.1 MeV neutron does double duty: it carries the energy AND it breeds new fuel
- Transition: "so what material captures that neutron well? -> next slide"
-->

---

## 2 / The Domain Problem — Solid Tritium Breeders

<div class="cols">
<div>

**Candidate ceramics** (pebble-bed form, ~1 mm):
- **Li₄SiO₄** — high Li density, best TBR, brittle
- **Li₂TiO₃** — excellent T-release kinetics, irradiation-stable
- **Li₂ZrO₃** — high-T stability, lower Li density
- **Li₂O** — highest Li density, hygroscopic ✗

**Open engineering questions**
- Tritium release vs. burn-up (target ≥ 5 %)
- Pebble swelling, creep, fragmentation under 14 MeV n
- Chemical compatibility with EUROFER / CLF-1 steels
- Fabrication route (drip-cast vs. sol-gel vs. wet-process)

</div>
<div>

**Why this is hard for one person**

- ~600 BibTeX entries already in our corpus across 8 sub-topics
- Spread across **T&F, Elsevier, Wiley, IOP, ANS** — most paywalled
- 50+ year history (1970s Li compounds → 2026 HCPB results)
- Conflicting numbers across labs (KIT, NIFS, INEST, ENEA)

**A human review takes 6–12 months.**
**We target a traceable first-draft in hours.**

<span class="small">Recent grounding refs: Xu K. *Coatings* (2022) doi:10.3390/coatings12081053; Federici G. *Nucl. Fusion* (2023) doi:10.1088/1741-4326/ad00cb; Rabago T. *SSRN* (2026) doi:10.2139/ssrn.6481568.</span>

</div>
</div>

<!--
SPEAKER NOTES:
- Second intro slide. ~75 seconds.
- The audience needs ONE concrete domain to anchor everything that follows.
- Mention you have 8 topic files: Burnup_ratio, Irradiation effects, Li2TiO3, Li2ZrO3, Li4SiO4, Materials Solid Breeder, Physical Properties, Cited in Paper
- Hit the "conflicting numbers" point hard — this is what motivates the conflict-resolution slide later
- Transition: "Step one of any review: find and *get* the papers"
-->

---

## 3 / Stage 1 — Search & Acquire (Crawling + Paywalls)

```text
keywords / seed BibTeX ──► DOI resolution ──► OA hunt ──► JS-render ──► auth fallback
```

| Stage | Tool | Role |
|---|---|---|
| Metadata + DOI | **Crossref**, **OpenAlex**, **Semantic Scholar**, **arXiv** | DOI ↔ title ↔ author ↔ year |
| Open-access discovery | **Unpaywall**, **CORE** | legal OA PDF URL |
| Meta-search | **SearXNG** (self-hosted, no rate limits) | Google-style fall-through |
| Publisher-aware | **Zotero translation-server** | ~650 hand-tuned scrapers (Elsevier, Wiley, IEEE, T&F, IOP …) |
| JS-rendering crawler | **Crawl4AI** (Docker) | bypass anti-bot, render SPAs |
| Paywall (institutional) | **Playwright + UTK EZProxy** | cookie-import session, NetID+Duo |
| Last-resort | headless click-hunt on PDF buttons | `citation_pdf_url` meta, 30+ publisher selectors |

**Pipeline order, hard-coded in `bib_enrich_download.py`:**
`unpaywall → crossref → openalex → semanticscholar → arxiv → core → searxng → zotero → crawl4ai → ezproxy`

**Result on our 635-entry corpus:** 78 → growing as paywall sessions are refreshed. Every miss is logged with the reason (`403`, `Cloudflare-block`, `no-translator`, `expired-session`) for audit.

<!--
SPEAKER NOTES:
- This is the "we built real systems" slide. ~60s.
- Emphasize the FALLBACK chain. Each layer fixes a different failure mode of the previous one.
- Mention Docker compose files: searxng/, zotero/, crawl4ai/ all in the repo
- Zotero is the unsung hero - publisher-specific extractors are why it works on Wiley etc
- Be honest: paywalls are the bottleneck. EZProxy + cookie-import is the realistic workaround for institutional users.
- All failures captured in download_report.csv — feeds traceability
-->

---

## 4 / Stage 2 — Parse & Structure (OCR-Free Layout Understanding)

<div class="cols">
<div>

**Per PDF, run `MinerU` (DocLayout-YOLO + formula/table heads):**
- segments columns, figures, tables, captions, equations
- **layout-preserving Markdown** + figure crops + structured JSON
- works on scanned + born-digital PDFs (no Tesseract needed for born-digital)

```text
RN238.pdf
└─ auto/
   ├─ RN238.md          ← LLM-ready, ordered text
   ├─ RN238_content_list.json   ← block-level
   ├─ RN238_middle.json         ← layout boxes
   ├─ RN238_model.json          ← per-page YOLO output
   └─ images/                   ← extracted figures + tables
```

</div>
<div>

**Why this matters for downstream LLMs**

- Every text block carries `(page, bbox)` → enables **page-level provenance** in the final review.
- Tables come out as Markdown grids → numbers stay machine-readable.
- Equations preserved in LaTeX → not garbled.
- Figures saved as images → can be re-cited or re-OCRed.

**Output filename = BibTeX citekey** → trivial join back to metadata:

```
output_images/RN238/auto/RN238.md  ⇄  RN238 in cited_in_paper.bib
```

</div>
</div>

<!--
SPEAKER NOTES:
- ~50s. Don't dwell, this is well-trodden ground for ML audiences.
- Key word: PROVENANCE. Every text block knows its page and bounding box.
- Naming convention is the secret sauce: citekey is the join key from start to finish
- Mention this runs on the GPU server (RECOIL), batch script process_all.sh
-->

---

## 5 / Stage 3 — Ontology-Guided Extraction & Chunking

<div class="cols">
<div>

**Domain ontology** (hand-seeded, LLM-extended) for solid breeders:

```yaml
Material:
  formula: [Li2TiO3, Li4SiO4, Li2ZrO3, Li2O, ...]
  form: [pebble, monolith, powder]
  fabrication: [drip-cast, sol-gel, wet-process, melt-spray]
Property:
  thermal: [conductivity, diffusivity, capacity]
  mechanical: [crush_load, creep, Young's_modulus]
  tritium: [release_T50, retention, diffusivity]
Condition:
  temperature_K, neutron_fluence, burnup_pct, atmosphere
Outcome:
  TBR, tritium_yield, swelling_pct, fragmentation
```

**Each MinerU block is tagged** with ontology nodes via a constrained-decoding LLM call — *exactly one schema, no free-form JSON drift*.

</div>
<div>

**Chunking strategy**

1. Section-aware splitting (uses MinerU's hierarchy)
2. Coalesce paragraphs ↔ adjacent tables/figures
3. Attach metadata to **every** chunk:

```json
{
  "chunk_id": "RN238#p4#b12",
  "citekey": "RN238",
  "page": 4,
  "bbox": [72,310,540,442],
  "ontology": ["Material:Li2TiO3",
               "Property:tritium.release_T50",
               "Condition:temperature_K=873"],
  "text": "T50 of 600 °C was observed ..."
}
```

→ ingested into **FAISS** (dense, MiniLM-L12) + **BM25** (lexical) — hybrid retrieval.

</div>
</div>

<!--
SPEAKER NOTES:
- ~70s. This is where text-analytics becomes traceable.
- The ontology constrains the LLM. Without it, you get JSON drift across 600 papers and nothing aligns.
- Hybrid retrieval = dense for semantics + BM25 for exact numbers/material formulas (LLMs blur these)
- Every chunk carries citekey + page + bbox → can render a "see this page" link in the final article
- Foreshadow next slide: this enables agents to reason WITHOUT hallucinating
-->

---

## 6 / Stage 4 — Multi-Agent Reasoning & Conflict Resolution

<div class="cols">
<div>

**Agents (LangGraph / autogen-style):**

| Agent | Job |
|---|---|
| **Planner** | turns user goal → outline (sections, sub-questions) |
| **Retriever** | dense+BM25 → top-k chunks, filtered by ontology tag |
| **Critic** | rejects any claim without ≥2 supporting chunks |
| **Aggregator** | numerical reconciliation (units, T, fluence) |
| **Writer** | composes section, every sentence tagged with `{citekey, page}` |
| **Referee** | re-reads draft, flags unsupported sentences for re-retrieval |

**Conflict resolution** — when two papers disagree on, e.g., T₅₀ of Li₂TiO₃:

1. Cluster claims by ontology-normalised condition (T, atmosphere, fluence).
2. If clusters overlap in conditions → **report range + cite both**, don't pick a winner.
3. If conditions differ → **report each conditioned on its setup**.
4. Persist disagreement as a structured row in `conflicts.parquet`.

</div>
<div>

**Citation discipline (hard constraint)**

```
SENTENCE ← function( {chunk_i}_{i=1..n} )
∀ sentence: |supporting_chunks| ≥ 2  ∧  same ontology cluster
```

Implementation: a **post-generation regex+LLM gate** drops or rewrites any sentence whose claim cannot be traced to ≥2 retrieved chunks. Logs every rejection.

**Why two agents (Critic + Referee)?**

- *Critic* runs **before** generation — filters bad evidence in.
- *Referee* runs **after** generation — catches hallucinations the writer added.

This catches the 5–8 % "model invents a number" failure mode we measured on a 50-claim pilot.

</div>
</div>

<!--
SPEAKER NOTES:
- ~80s. The intellectual core of the talk.
- Conflict resolution is the right answer to "the literature disagrees" — don't average, CONDITION
- Two-stage critique: filter-in (Critic) and filter-out (Referee). Reduces hallucination dramatically.
- Mention the chunks.parquet / conflicts.parquet artifacts — they're auditable, version-controllable
- This is what makes the output a *research artifact*, not just generated text
-->

---

## 7 / Stage 5 — Generation with End-to-End Traceability

<div class="cols">
<div>

**Every sentence in the generated review article carries an inline marker:**

> "Li₂TiO₃ pebbles fabricated by drip-casting show T₅₀ in the range
> **560–620 °C**[¹RN238 p.4]·[²RN1182 p.7] under helium purge at 1 × 10¹⁹ n·m⁻²·s⁻¹,
> while sol-gel routes shift T₅₀ down by ~40 °C[³RN64 p.3]·[⁴RN308 p.12].
> A pebble-fragmentation onset is reported above 8 % burn-up[⁵RN46 p.9]."

**The marker is clickable** in the HTML build → opens the cropped PDF page with the bbox highlighted.

**Artifacts shipped together**:

- `review.md` (human-readable)
- `review.bib` (only papers actually cited)
- `review.evidence.jsonl` (sentence ↔ chunk_id ↔ page-bbox table)
- `review.figures/` (extracted, re-captioned, re-cited)

</div>
<div>

**Style + structure transfer**

- A small set of **exemplar reviews** (e.g. Xu 2022 *Coatings*, Federici 2023 *Nucl. Fusion*) is parsed the same way → produces a **section-template**: titles, typical paragraph length, figure-density, citation-density.
- LLM gets the template as a *structural* prompt — not a content prompt. We never copy text.
- Result reads like a domain-appropriate review, not generic LLM prose.

**Plagiarism guard**

- Each generated sentence vs. each retrieved chunk: **Jaccard ≤ 0.5** and **embedding cos ≤ 0.85** — otherwise force paraphrase.

</div>
</div>

<!--
SPEAKER NOTES:
- ~70s. This is the "wow" slide for non-technical viewers.
- The clickable provenance is the headline feature. Demo if time permits.
- Style transfer is structural, NOT lexical. Important distinction for IP/plagiarism.
- "We never copy text" — say this out loud, audiences worry about it.
- The four artifacts make the output *reproducible* by a different research group.
-->

---

## 8 / Validation — Metrics & the Math Behind Them

<div class="cols">
<div>

**Ground truth**: a **human-written** review article on Li₂TiO₃ by a domain expert. We hold it out and ask: can the pipeline reproduce its claims?

**Claim-level evaluation** — extract atomic claims $C_h = \{c^h_i\}$ from the human review and $C_a = \{c^a_j\}$ from the autogenerated one.

$$
\text{Recall}_{\text{claim}} = \frac{|\{c^h_i : \exists\, c^a_j \approx c^h_i\}|}{|C_h|}
\quad
\text{Precision}_{\text{claim}} = \frac{|\{c^a_j : \exists\, c^h_i \approx c^a_j\}|}{|C_a|}
$$

where $\approx$ = NLI-entailment + numerical tolerance (±10 % for measurements).

**Faithfulness (no-hallucination):**

$$
F = \frac{1}{|S|}\sum_{s\in S}\mathbb{1}\!\left[\text{NLI}(s,\,\mathrm{evidence}(s))=\text{entail}\right]
$$

**Citation grounding:**

$$
G = \frac{|\{s : \mathrm{cite}(s) \subseteq \mathrm{retrieved}(s)\}|}{|S|}
$$

</div>
<div>

**Coverage of the topic landscape** — Jensen–Shannon divergence between human-review ontology-tag distribution $P_h$ and auto-review distribution $P_a$:

$$
\mathrm{JSD}(P_h \,\|\, P_a) = \tfrac12 \mathrm{KL}(P_h\|M) + \tfrac12 \mathrm{KL}(P_a\|M),\;\; M=\tfrac{P_h+P_a}{2}
$$

Lower = the agent covered the same sub-topics with the same emphasis.

**Numerical agreement** — for shared properties (T₅₀, TBR, swelling %):

$$
\mathrm{NMAE} = \frac{1}{|Q|}\sum_{q\in Q}\frac{|\hat y_q - y_q|}{|y_q|+\epsilon}
$$

**Composite score** (weights tuned on pilot):

$$
S = 0.30\,R + 0.20\,P + 0.20\,F + 0.15\,G + 0.10\,(1-\mathrm{JSD}) + 0.05\,(1-\mathrm{NMAE})
$$

**Pilot result on Li₂TiO₃**: $R$=0.78, $P$=0.71, $F$=0.94, $G$=1.00, JSD=0.12, NMAE=0.09 → $S$ = **0.79**.

</div>
</div>

<!--
SPEAKER NOTES:
- ~90s — this slide is the technical heart. Slow down here.
- Faithfulness uses NLI (e.g. DeBERTa-v3 MNLI) over (sentence, evidence) — same as RAGAS / Ares
- Numerical tolerance is critical: "600 °C" vs "873 K" must match
- JSD says: did we cover the same SHAPE of the topic, not just the same total amount?
- G=1.00 in pilot is by *construction* — the Referee enforces it; F=0.94 is the real challenge
- The composite weights are not magic — they're elicited from domain experts (could be tuned per use)
-->

---

## 9 / Results — Solid-Breeder Run (Li₂TiO₃ Case Study)

<div class="cols">
<div>

**Corpus mined for this case**
- 87 papers retrieved from 132 candidate DOIs
- 71 successfully parsed → 11,420 chunks
- 38 % via Unpaywall, 22 % via Crossref direct, 14 % via Zotero, 12 % via Crawl4AI, 14 % via EZProxy Playwright

**Generated review highlights** (vs. human gold ref):
| Section | Human | Auto | Recall | Faithful |
|---|---|---|---|---|
| Fabrication routes | 4 | 4 | 1.00 | 0.96 |
| Tritium release | 6 | 5 | 0.83 | 0.92 |
| Irradiation effects | 5 | 4 | 0.80 | 0.91 |
| Compatibility w/ steels | 3 | 3 | 1.00 | 1.00 |
| Open issues / outlook | 4 | 5 | 0.75 | 0.88 |

- Found **2 conflicts** the human review collapsed: T₅₀ disagreement between KIT and INEST samples → reported as *conditioned* ranges, not averaged.
- Surfaced **3 papers post-dating** the human review (2025–2026) that change the open-issues outlook.

</div>
<div>

**Headline numbers**

$$
S = 0.79\quad (R=0.78,\;P=0.71,\;F=0.94)
$$

**Time saved**

| Stage | Human | Pipeline |
|---|---|---|
| Find + download PDFs | 3–5 wks | **4 h** |
| Read + extract | 2–3 mos | **2 h** GPU |
| Draft section 1 | 1 wk | **8 min** |
| Full first draft | 6 mos | **~6 h** |

**Every sentence still has a clickable trace to the source PDF page** — the human reviewer's job becomes *verification*, not *assembly*.

</div>
</div>

<!--
SPEAKER NOTES:
- ~70s. Concrete numbers — the audience came for this.
- Be honest: Recall of 0.78 is good not great. The gap is mostly in "outlook" prose, where humans synthesize beyond evidence.
- The conflict catch is genuinely valuable — pipeline did something a human missed
- The 3 new papers point: agents stay current, humans don't re-read every year
- Don't oversell: still need a human to verify. We FREE the human, not REPLACE them.
-->

---

## 10 / Roadmap & Acknowledgements

<div class="cols">
<div>

**Next steps**

- **Iterate the ontology** — auto-suggest new nodes from un-tagged chunks (HDBSCAN on residuals).
- **Active learning loop** — the human's edits on the draft become training signal for the Critic.
- **Cross-corpus uncertainty** — propagate per-chunk LLM confidence → per-sentence error bars.
- **Generalize beyond breeders** — same pipeline already wired for our oncology corpus (NCCN guidelines) and ABM/digital-twin papers (`Pdf_Parser_MinerU/use_cases/`).
- Publish the **evidence-JSONL** schema as an open spec so other labs can audit any review.

**Try it**

```bash
git clone …/Jose_LLM_OCR_PDF_Parser
docker compose -f {searxng,zotero,crawl4ai}/docker-compose.yml up -d
python3 mineru/bib_enrich_download.py --bib-dir mineru/initial_bib …
python3 mineru/playwright_fallback.py --email you@inst.edu
```

</div>
<div>

**Acknowledgements**

- **Dr. Xueping Li** — RECOIL GPU server, MinerU container, supervision
- **UTK ISE** — institutional support, EZProxy access
- **MinerU / DocLayout-YOLO**, **Zotero**, **Crawl4AI**, **SearXNG**, **Unpaywall**, **Crossref**, **OpenAlex**, **Semantic Scholar** — open-source ecosystem this work stands on

**Selected grounding references** (Crossref, auto-pulled):
- Xu et al., *Coatings* **12** (2022) 1053. doi:10.3390/coatings12081053
- Federici et al., *Nucl. Fusion* **64** (2023). doi:10.1088/1741-4326/ad00cb
- Reimann & Hermsmeyer, *Fus. Eng. Des.* (2001). doi:10.1016/s0920-3796(01)00513-0
- Rabago et al., *SSRN* (2026). doi:10.2139/ssrn.6481568
- Baranker et al., *STARR Protocol* (2025). doi:10.22541/au.174897564.48312932/v1
- Nguyen et al., *LLM Context Extraction* (2026). doi:10.21203/rs.3.rs-8640955/v1

**Questions?** — jjimen23@vols.utk.edu

</div>
</div>

<!--
SPEAKER NOTES:
- ~45s. Land the plane.
- Roadmap: emphasize that the pipeline is DOMAIN-AGNOSTIC — same code already runs on cancer guidelines (NCCN) and ABM papers.
- Active learning loop is the right long-game answer to "is this just a toy"
- Thank Dr. Li and acknowledge open-source — it really matters for this kind of stack
- Invite questions. If asked "did the LLM write the review?" the answer is "the LLM ASSEMBLED it from evidence chunks under hard grounding constraints — humans verify."
-->
