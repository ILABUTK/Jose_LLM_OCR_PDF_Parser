# Paper Generation Pipeline

End-to-end pipeline that ingests a reference scientific paper (Markdown from
MinerU OCR), extracts two ontologies (structure + style), drafts a new paper
on a chosen topic via a LangGraph multi-agent system, validates the result
with quantitative metrics, and renders it as Elsevier LaTeX.

```
Reference .md
     │
     ▼
[01_extract_ontologies] ──▶ ontologies/structure_ontology.json
                        └─▶ ontologies/style_ontology.json
     │
     ▼
[02_plan_paper]  ──▶ output/outline.json
     │
     ▼
[03_agents_write]   Writer ↔ Critic ↔ Judge   (LangGraph)
     │                                          ──▶ output/draft_sections.json
     ▼
[04_validate]   structural_fidelity, semantic_grounding,
                citation_coverage, style_alignment,
                conflict_metrics, composite_quality
                                                ──▶ output/validation_report.json
     │
     ▼
[05_render_elsevier]                            ──▶ output/paper.tex
```

## Backend

Remote Ollama at `https://ollama.viridian.ise.utk.edu` (HTTP Basic auth).
Models:
- `qwen3-next:thinking` — planner / writer / critic / judge
- `qwen3-coder:latest`  — LaTeX rendering
- `nomic-embed-text`    — grounding similarity

## Install

```bash
source /home/jose/Jose_LLM_OCR_PDF_Parser/venv/bin/activate
cd /home/jose/Jose_LLM_OCR_PDF_Parser/paper_generation
pip install -r requirements.txt
python ollama_client.py        # smoke-test connection
```

## Run

```bash
python 01_extract_ontologies.py
python 02_plan_paper.py --topic "Lithium orthosilicate as tritium breeder: a comparative review with Li2TiO3 and Li2ZrO3"
python 03_agents_write.py
python 04_validate.py
python 05_render_elsevier.py
```

## Math behind validation

- **Structural fidelity** $S = \frac{|B_{ref} \cap B_{gen}|}{|B_{ref} \cup B_{gen}|}$
  where $B$ are bags of `(level, role)` tuples.
- **Semantic grounding** $G = \frac{1}{N}\sum_i \max_j \cos(e(c_i), e(r_j))$
  with $e(\cdot)$ from `nomic-embed-text`.
- **Citation coverage** $C = \frac{|\{c_i : \text{has citation token}\}|}{|\{c_i\}|}$
- **Style alignment** $A = \frac{1}{1 + \tfrac12(KL(P\|Q)+KL(Q\|P))}$
  over marker distributions from `style_ontology.json`.
- **Composite quality** $Q = \tfrac14(S+G+C+A)$.

## Multi-agent framework

[LangGraph](https://langchain-ai.github.io/langgraph) — the well-known
stateful graph orchestrator. The Writer–Critic–Judge pattern is a standard
agent-debate pattern (Du et al. 2023, "Improving Factuality and Reasoning
via Multiagent Debate"). Conflicts (verdict < 0.75) trigger another writer
round; after `MAX_ROUNDS`, a Judge agent at temperature 0 produces the final
text and records its rationale for traceability.
