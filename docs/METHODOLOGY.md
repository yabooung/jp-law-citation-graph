# How JLaw-CiteGraph is built

A practical description of the pipeline, the resolution rules, and the honest quality picture.
For *using* the data start with the [README](../README.md); for the data schema see
[DATA_CARD](../DATA_CARD.md).

## Pipeline

```
e-Gov law XML  →  parse (条/項/号)  →  extract citations  →  resolve to a law  →  export
```

Fully **deterministic**: no LLM, no randomness. The same e-Gov snapshot + the same code produce a
byte-identical graph. Reproduce with `src/build_graph.py` (see README).

## Extraction

Rule-based, over the parsed article text. It finds:
- internal refs (`第N条`, `第N条の2`, `第N条第M項第K号`),
- external refs (`法令名（promulgation）第N条`, and bare `法令名第N条`),
- ranges (`第N条から第M条まで`), enumerations, and referential forms (`前条`/`同条`/…).

## Resolution

Each captured law-name string is resolved to a `law_id`, trying paths in order and recording **which
path won** (`via`) plus a `confidence`:

| via | how | confidence |
|---|---|---|
| `promulgation` | exact 法令番号 match | 1.0 |
| `canonical` | exact current law name | 1.0 |
| `old_name` | renamed law (e-Gov 旧法令名) | 0.95 |
| `prefix_stripped` | 新/旧/改正後の + name | ~0.95 |
| `alias` | known/standard abbreviation | 0.9 |
| `local_def` | abbreviation defined in the same document | 0.9 |
| `local_def_tail` | clause-wrapped 新法/旧法 → in-document definition | 0.85 |
| `suffix` | fuzzy trailing match (rare) | 0.85 |

A few rules are worth calling out:

- **Over-grab trim.** The extractor sometimes captures leading clutter (`第六十二条中租税特別措置法`).
  We trim to the longest suffix that is a real law name (`租税特別措置法`), which also frees the
  swallowed internal ref. A **boundary guard** blocks the dangerous inverse — collapsing a compound or
  repealed name onto a shorter *different* current law (`失業保険法`→`保険法`) — by only trimming at a
  clause / particle / version boundary, never mid-compound. (An audit traced this collapse class; the
  guard removes ~5,600 false edges while keeping version refs like `旧国民年金法`→`国民年金法`.)

- **In-document anaphora.** 附則 define local labels (`…改正前の○○法（以下「旧法」という。）`); we map
  `旧法`/`新法` (incl. clause-wrapped forms) to the defined law, scoped to that document.

- **Corpus-mined abbreviations.** Instead of hand-curating, we harvest the corpus's own definitions
  (`金融商品取引法（…以下「金商法」という。）`) and keep an abbreviation only when *standard* — defined
  in ≥2 distinct laws all pointing to the same law, specific, and free of version/clause prefixes. This
  yields 22 audit-backed abbreviations (`感染症法`, `労災保険法`, `国共済法`, `精神保健福祉法`, …),
  recovering ~2,700 genuine cross-law edges where a law uses a standard abbreviation without defining it.
  Reproduce with `src/mine_abbreviations.py`; the result is merged into `jlawcite/jp_law_aliases.json`.

## Quality (honest)

- **Precision** — on a via-stratified sample (400 edges, 50 per path) we found **0 confirmed errors**,
  and a 64-edge human spot-check found none either. This is **preliminary**: labels were LLM-proposed
  with a human spot-check, *not* a blind multi-annotator round, and 50/path only bounds the error rate
  to roughly ≤6% per path. We report "0 confirmed errors," not a point precision.
- **Recall** — **68% raw** (1,212,708 of 1,783,702 extracted external citations resolve). Most of the
  unresolved 32% is *not* lost citations: it's extraction artifacts / co-references and out-of-scope
  targets (repealed/treaty/foreign laws that have no node in a current-only corpus). The graph is a
  high-precision **lower bound**, not an exhaustive census.
- **Confidence tiers** — `canonical` + `promulgation` (~75% of edges) are exact matches and near-certain.
  The rest carry their `via`/`confidence` so you can filter to whatever trust level you need.

To turn the *preliminary* precision/recall into validated measurements, see
[`eval/EVAL_PROTOCOL.md`](../eval/EVAL_PROTOCOL.md) (blind multi-annotator labeling + a larger gold).

## Limitations

- **Lower bound, not exhaustive** — high precision, partial recall. Absence of an edge ≠ "no citation."
- **Current-version collapse** — ~22% of edges are version-bound (`旧法`/`改正前`) and map to the current
  version; not suitable for amendment-propagation analysis without a version layer.
- **National statutes only** — no local ordinances (条例) or case law.
- **Dated snapshot** — 2026-06-23; regenerate with `src/fetch_egov.py` for a current graph.

## A note on evaluation

While characterizing this graph we repeatedly found that quick automatic heuristics gave
confident-but-wrong answers (a promulgation-based precision proxy was confounded; "main provisions
resolve better than 附則" was the reverse; an LLM-labeled recall read swung from 78% to 93% between
samples). Each was only caught by reading examples by hand. The practical takeaway, baked into the
`eval/` harness: for citation resolution — where wrong answers look plausible — trust human-labeled
samples over automatic proxies.
