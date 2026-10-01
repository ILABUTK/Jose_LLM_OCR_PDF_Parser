# Restructured Paper-Generation Pipeline

A single `docker-compose` stack that turns **a folder of PDFs + references** and
**a research hypothesis** into a grounded review paper, using **graph-of-thought
reasoning** driven by **MCP agents** and illustrated with **ComfyUI**.

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
                                              │   │ image  / writing     │   │
   external vLLM  ◀── LLM_BASE_URL ───────────│   └──────────────────────┘   │
   (ornl-qwen3-8-27b)                         │  comfyui  :8188 (GPU)        │
                                              └──────────────────────────────┘
                                                        │
                                                 outputs/ (paper.md, graph, figures)
```

### Inputs
| File | Purpose |
|------|---------|
| `inputs/hypothesis.json` | research hypothesis + research questions |
| `inputs/keywords.json`   | keyword list |
| `inputs/style.*`         | a previous paper by the author (style reference) |
| `inputs/pdfs/`           | the corpus PDFs |
| `inputs/*.bib` / `*.enw` / `*.ris` | references (BibTeX or EndNote/RIS) |

### LLM engine
We connect to an existing **vLLM** instance over its OpenAI-compatible
`/v1/chat/completions` endpoint (the `llmlite` custom endpoint, model
`ornl-qwen3-8-27b`). Configure via `.env`:

```
LLM_BASE_URL=https://<ngrok-host>/v1
LLM_MODEL=ornl-qwen3-8-27b
LLM_API_KEY=<secret>
```

### MCP agents
`run_pipeline.sh`'s stages are re-expressed as four MCP servers under
`orchestrator/mcp_servers/`:

| Agent | Tools |
|-------|-------|
| `corpus`    | `list_papers`, `search_evidence`, `get_figures`, `short_ref` |
| `reasoning` | `expand_idea`, `validate_claim`, `build_graph` |
| `image`     | `comfy_health`, `generate_figure`, `image_count` |
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
When a node is well-developed, the `image` agent asks **ComfyUI** for
`PAPER_IMAGE_COUNT` figures. If the node relies on a paper that ships its own
figures, one of **that paper's own images** is fed back in as an img2img
reference.

## Usage

```bash
cd restructure
cp .env.example .env            # set LLM_BASE_URL / LLM_API_KEY
# drop your PDFs into inputs/pdfs/ and a references.bib / *.enw next to them

docker compose up -d --build
docker compose logs -f orchestrator
```

Outputs land in `outputs/`:
- `reasoning_graph.json` — the full graph-of-thought (scores, evidence, figures)
- `draft_sections.json`  — per-section drafts + citekeys
- `paper.md`             — assembled review paper
- `figures/`             — generated figures

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
