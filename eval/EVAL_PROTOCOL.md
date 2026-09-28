# Evaluation protocol — turning preliminary figures into validated measurements

`docs/METHODOLOGY.md` reports **preliminary** precision/recall (LLM-proposed labels, small recall gold).
This is the protocol to upgrade them to validated, review-grade measurements. It requires **human
annotation** (the one thing the pipeline cannot self-supply).

## A. Precision — blind multi-annotator + κ
Goal: independent confirmation, free of confirmation bias.
1. ≥2 annotators label `precision_sample.csv` (50 edges × 8 resolution paths = 400) **blind** — i.e.
   *without* seeing the system's proposed verdict. (Use a labeling UI that hides the system label.)
   For each edge mark **O** (resolved law is correct) / **X** (wrong) / **?** (unsure).
2. Run `python compute_kappa.py <annotatorA.csv> <annotatorB.csv>` → inter-annotator agreement + Cohen's κ.
   κ ≥ 0.8 indicates reliable labels.
3. Run `python aggregate_precision.py` → per-path precision with Wilson CIs.
> Reports a *measured* precision with a confidence interval, replacing "0 confirmed errors."

## B. Recall — larger labeled gold
Goal: replace the n=32 estimate with a tight interval.
1. A human labels `recall_gold_sample.csv` (300 chunks, 附則-oversampled). For each chunk, read the
   text and mark, in `missed_count` / `missed_notes`, any **external** (law-to-law, article-level)
   citation the system did **not** capture (column `system_found`). Intra-law (same-law) references
   are out of scope, matching prior work.
2. Recall = found / (found + missed), with a Wilson CI over the (now larger) sample, broken down by
   section (main vs 附則).
> Replaces the §5 "~85–90% estimate" with a measured recall + CI.

## C. What "passing" looks like
- Precision: measured value + κ ≥ 0.8 + Wilson CI (not "0 confirmed errors").
- Recall: measured value + CI on ≥300 chunks (not n=32).
- Both reported per resolution path / section, with the out-of-scope (OOS) denominator stated.

Files: `precision_sample.csv`, `recall_gold_sample.csv`, `compute_kappa.py`, `aggregate_precision.py`.


## v2 additions (`eval/v2/`)
- `nta_gold.jsonl`: 1,700 NTA 質疑応答事例 cases, 1,170 with article-level answers. It serves as the
  retrieval benchmark (`jlawcite eval` → `nta_retrieval_results.json`).
- `precision_template_v2.csv`: 20 random edges per resolution rule from the v2 graph, with source
  context, for the blind precision round described in §A. Label column `label_O_X` is empty.
  The preliminary v2 figures in `docs/METHODOLOGY.md` came from a non-blind check during development.
- The v1 files (`precision_sample.csv`, `recall_gold_sample.csv`) refer to the v1 graph.
