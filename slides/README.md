# Slides — Traceability-Grounded Literature Pipeline

10-slide Marp deck for the 10-minute talk on the BibTeX → PDF → MinerU → grounded-review pipeline,
case-studied on solid tritium-breeder materials (Li₂TiO₃, Li₄SiO₄, Li₂ZrO₃).

## File

- [pipeline_deck.md](pipeline_deck.md) — Marp Markdown source (10 slides, KaTeX math, two-column layouts, speaker notes in HTML comments)

## Build

### Option A — one-shot via Docker (no install)

```bash
# HTML
docker run --rm --init -v "$PWD":/home/marp/app marpteam/marp-cli pipeline_deck.md

# PDF
docker run --rm --init -v "$PWD":/home/marp/app marpteam/marp-cli pipeline_deck.md --pdf --allow-local-files

# PPTX (editable in PowerPoint / Keynote)
docker run --rm --init -v "$PWD":/home/marp/app marpteam/marp-cli pipeline_deck.md --pptx --allow-local-files
```

### Option B — local Marp CLI

```bash
npm install -g @marp-team/marp-cli
marp pipeline_deck.md --pdf --allow-local-files
marp pipeline_deck.md --pptx --allow-local-files
marp pipeline_deck.md --html --allow-local-files
```

### Option C — VS Code

Install the **Marp for VS Code** extension (`marp-team.marp-vscode`),
open `pipeline_deck.md`, and use the preview button (top-right) or
"Marp: Export slide deck…" command.

## Speaker notes

Speaker notes are embedded as HTML comments (`<!-- SPEAKER NOTES: … -->`)
inside each slide. They are:

- visible in Marp's presenter mode (`p` key during HTML presentation)
- exported into PPTX speaker-notes pane
- ignored by the PDF/HTML render

## Timing target

10 minutes / 10 slides = ~1 min/slide on average. The deck is intentionally
front-loaded: slides 1–2 are introduction-heavy (~75 s each), slides 3–7
are the technical pipeline (~60–80 s each), slides 8–9 are validation +
results (~70–90 s), slide 10 is a fast close (~45 s).

## References pulled live from Crossref

The grounding citations on slides 2 and 10 were pulled from
the Crossref REST API on the day the deck was drafted. To refresh
or add more:

```bash
curl -s "https://api.crossref.org/works?query=Li2TiO3+tritium+breeder&rows=5&select=DOI,title,author,issued,container-title" \
     -H "User-Agent: YourTool/1.0 (mailto:you@inst.edu)" | jq .
```


