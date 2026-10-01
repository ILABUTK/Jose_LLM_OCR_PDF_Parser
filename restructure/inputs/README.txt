Place your corpus and the author's previous paper here, then run the stack.

Expected layout:

  inputs/
    hypothesis.json     # research hypothesis + research questions + title/journal
    keywords.json       # keyword list
    style/              # the author's previous paper, MinerU-parsed (a <name>/hybrid_auto/<name>.md tree)
    pdfs/               # the corpus, MinerU-parsed (one <name>/hybrid_auto/<name>.md per paper)

No .bib / EndNote file is needed — references are built automatically from the
MinerU-parsed papers (the folder name is used as the citation key and the
document's first heading as its title).

Only hypothesis.json, keywords.json and pdfs/ are required. If style/ is absent
a generic formal review voice is used.

Output (in ../outputs/): paper.tex + elsarticle.cls (Elsevier manuscript),
paper.pdf (if LaTeX is available), plus paper.md and the reasoning graph.
