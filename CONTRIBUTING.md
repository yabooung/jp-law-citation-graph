# Contributing to JLaw-CiteGraph

Thanks for your interest — issues and pull requests are welcome.
日本語・한국어での Issue / PR も歓迎・환영합니다.

## Ways to help (the roadmap)

The project's honest limitations *are* the roadmap. High-value contributions, roughly in order:

1. **Blind annotation round — turns preliminary metrics into validated ones.**
   Precision and recall are currently **preliminary** (LLM-proposed labels + a small human
   spot-check). The single most valuable contribution is an *independent, blind* labeling round:
   - **Precision:** for each edge in `eval/precision_sample.csv`, judge whether the resolved law is
     correct (O / X / unsure) **without** looking at the system's answer.
   - **Recall:** for each chunk in `eval/recall_gold_sample.csv`, mark any *external* (law-to-law)
     citation the system missed.
   - Then run `eval/compute_kappa.py` (inter-annotator agreement) and `eval/aggregate_precision.py`.
   - Full protocol: [`eval/EVAL_PROTOCOL.md`](eval/EVAL_PROTOCOL.md). This needs ≥2 annotators.

2. **Version-aware layer.** ~22% of edges are version-bound (`旧法` / `改正前`) and currently collapse
   to the *current* version. Resolving them to specific versions would enable amendment-propagation
   analysis — a frequently-requested use case the current graph cannot support.

3. **Coverage.** Local ordinances (条例), case law, or expanding the standard-abbreviation dictionary
   (`src/jlawcite/jp_law_aliases.json`; abbreviations are mined by `src/mine_abbreviations.py`).

4. **Report data issues.** A wrong edge or a missing citation is valuable signal — open an issue with
   the **data issue** template (`.github/ISSUE_TEMPLATE/`). Include the source law/article, the
   target, and an e-Gov link or quoted text if you can.

## Dev setup

Core pipeline is pure Python standard library (3.10+), no third-party dependencies.

```bash
cd src
# reproduce the graph from an e-Gov snapshot directory (deterministic)
python build_graph.py --corpus <snapshot dir> --out ../data/
# (or fetch a fresh snapshot first: python fetch_egov.py --out snapshot/)
```

The MCP server has its own dep: `pip install -r mcp/requirements.txt`.

## Guidelines

- **Keep the pipeline deterministic** — no LLM and no randomness in resolution. Reproducibility
  (same snapshot + same code → identical output) is a core property, not negotiable.
- **New resolution paths** must carry a `via` label and a `confidence`, so users can trust-filter.
- **Precision over recall** — prefer missing an edge to emitting a wrong one (the graph is a
  high-precision lower bound by design).
- **Back data/graph claims with how you measured** — measurement scripts live in `src/` and `eval/`.
  A claimed number with no reproducible script won't be merged.
- Match the surrounding code style; keep comments in English.

## Reporting / questions

Use the issue templates in `.github/ISSUE_TEMPLATE/`:
- **Data issue** — a wrong or missing citation edge.
- **Bug report** — something in the code/pipeline.
- **Feature / help wanted** — an idea, or an offer to take on a roadmap item.
