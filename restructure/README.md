# Restructured Paper-Generation Pipeline

A single `docker-compose` stack that turns **a folder of PDFs + references** and
**a research hypothesis** into a grounded review paper, using **graph-of-thought
reasoning** driven by **MCP agents** and illustrated with **LLM-drawn SVG
figures** (no GPU/ComfyUI service).

> `searxng`, `crawl4ai`, `zotero` and `mineru` have been removed. The vLLM LLM
> engine is **not** part of this stack — we only connect to a pre-provisioned
> instance.

## Architecture

```
            inputs/ (mounted)                         docker-compose stack
  ┌───────────────────────────────┐          ┌──────────────────────────────┐
  │ hypothesis.json               │          │  orchestrator                │
  │ keywords.json                 │──mount──▶ │  ├─ pipeline.py (graph CoT)  │
  │ style.(tex|md|pdf)            │          │  └─ agent.py  (MCP agents)   │
  │ pdfs/*.pdf                    │          │        │ MCP stdio           │
  │ references.bib | *.enw | *.ris│          │   ┌────┴─────────────────┐   │
  └───────────────────────────────┘          │   │ corpus / reasoning / │   │
                                              │   │ figure  / writing    │   │
   external vLLM  ◀── LLM_BASE_URL ───────────│   └──────────────────────┘   │
   (ornl-qwen3-8-27b)                         │   (figures = LLM-drawn SVG)  │
                                              └──────────────────────────────┘
                                                        │
                                                 outputs/ (paper.md, graph, figures)
```

### Inputs
| File | Purpose |
|------|---------|
| `inputs/hypothesis.json` | research hypothesis + research questions + title/journal |
| `inputs/keywords.json`   | keyword list |
| `inputs/style/`          | the author's previous paper, MinerU-parsed (`<name>/hybrid_auto/<name>.md`) |
| `inputs/pdfs/`           | the corpus, MinerU-parsed (one `<name>/hybrid_auto/<name>.md` per paper) |

No `.bib` / EndNote file is required — references are built automatically from
the MinerU-parsed papers (folder name → citation key, first heading → title).

### LLM engine
We connect to an existing **vLLM** instance over its OpenAI-compatible
`/v1/chat/completions` endpoint (the `llmlite` custom endpoint, model
`ornl-qwen3-8-27b`). Configure via `.env`:

```
LLM_BASE_URL=https://<ngrok-host>/v1
LLM_MODEL=ornl-qwen3-8-27b
LLM_API_KEY=<your-secret-key>
```

### MCP agents
`run_pipeline.sh`'s stages are re-expressed as four MCP servers under
`orchestrator/mcp_servers/`:

| Agent | Tools |
|-------|-------|
| `corpus`    | `list_papers`, `search_evidence`, `get_figures`, `short_ref` |
| `reasoning` | `expand_idea`, `validate_claim`, `build_graph` |
| `figure`    | `svg_health`, `generate_figure`, `image_count` |
| `writing`   | `draft_section`, `critique_section` |

`agent.py` launches these over stdio and lets the vLLM model orchestrate them
via tool-calling (`PIPELINE_MODE=agent`). `pipeline.py` is the deterministic
counterpart that calls the same primitives directly (`PIPELINE_MODE=pipeline`).

### Graph-of-thought reasoning (`GRAPH_DEPTH`)
Reasoning is a **graph, not a chain**. From the hypothesis we seed top-level
ideas; each idea is **expanded** into sub-ideas, **grounded** in corpus
evidence, **validated** with a support score, and **compared** against its
siblings — recursing `GRAPH_DEPTH` levels deep (`GRAPH_BRANCHING` children per
node). Weakly-supported branches are pruned.

### Figures (`PAPER_IMAGE_COUNT`)
When a node is well-developed, the `figure` agent asks the **LLM** to draw
`PAPER_IMAGE_COUNT` publication-quality **SVG** figures (schematics/plots),
grounded in the node's retrieved corpus evidence. No GPU or ComfyUI service is
required; figures are vector files that embed directly in Markdown/LaTeX.

## Usage

```bash
cd restructure
cp .env.example .env            # set LLM_BASE_URL / LLM_API_KEY
# drop your MinerU-parsed corpus into inputs/pdfs/ and the author's paper into inputs/style/

cd /home/cloud/Jose_LLM_OCR_PDF_Parser/restructure
docker compose up -d --build --force-recreate orchestrator
docker compose logs -f orchestrator
```

Outputs land in `outputs/`:
- `paper.tex` + `elsarticle.cls` — the Elsevier (elsarticle) manuscript
- `paper.pdf`            — compiled PDF (when the LaTeX toolchain is present)
- `paper.md`             — assembled review paper (Markdown)
- `reasoning_graph.json` — the full graph-of-thought (scores, evidence, figures)
- `draft_sections.json`  — per-section drafts + citekeys
- `figures/`             — generated SVG figures (and their PDF conversions)

### Tuning
| Variable | Default | Meaning |
|----------|---------|---------|
| `GRAPH_DEPTH` | 3 | how deep each node is delved |
| `GRAPH_BRANCHING` | 3 | sub-ideas per node |
| `PAPER_IMAGE_COUNT` | 2 | figures per developed node |
| `PIPELINE_MODE` | pipeline | `pipeline` \| `agent` \| `idle` |

### Run a single stage locally (without Docker)
```bash
cd orchestrator
pip install -r requirements.txt
python llm_client.py            # smoke-test the vLLM connection
python pipeline.py --graph-only # build just the reasoning graph
python pipeline.py              # full run
python agent.py                 # MCP-agent-driven run
```


```


```
