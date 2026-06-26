# Data Card — JLaw-CiteGraph

## Source
- **e-Gov 法令検索** (https://laws.e-gov.go.jp/) — official Japanese government law database (Digital Agency / MIC).
- **Snapshot date**: 2026-06-23 (all national laws retrievable that day).
- Japanese statutes are not subject to copyright; e-Gov 法令データ is reusable with attribution.

## Scope
- **Included**: national statutes — laws (法律), cabinet orders (政令), ministerial ordinances (省令/府令),
  rules (規則), and their施行令/施行規則. **8,980 distinct laws** (10,229 e-Gov XML files incl. versions).
- **Excluded**: local ordinances (条例), case law (判例), administrative guidance, treaties as nodes
  (treaty *citations* exist in text but resolve to no node), books/commentary.

## Nodes
- One node per law (`law_id` = e-Gov 法令ID). Metadata: name, type (法令種別), e-Gov URL.
- (Article-level internal structure is used during extraction; the released `cites_edges` carry
  `src_article`/`tgt_article` strings.)

## Edges
- **Cross-law (`cites_law_to_law.csv`)**: directed `src_law → tgt_law`, weighted by citation count. Self-loops excluded.
- **Full (`cites_edges.jsonl.gz`)**: every resolved external citation with article paths, `via`, `confidence`.
- `via` = resolution path; filter for trust:
  | via | meaning | confidence |
  |---|---|---|
  | canonical | exact current law name | 1.0 |
  | promulgation | matched by 法令番号 | 1.0 |
  | old_name | renamed law (旧法令名) | 0.95 |
  | alias | known abbreviation | 0.9 |
  | local_def | in-document definition | 0.9 |
  | prefix_stripped | 新/旧/改正後の + name | ~0.95 |
  | local_def_tail | clause-wrapped 新法/旧法 | 0.85 |
  | suffix | fuzzy trailing match (rare) | 0.85 |

## Construction (deterministic)
e-Gov XML → parse (条/項/号) → rule-based citation extraction (法令番号, 法令名, abbreviation,
enumeration, range) → resolution (dictionary-anchored over-grab trim, in-law definition anaphora,
renamed-law mapping) → export. No LLM, no randomness. Same snapshot + code → identical output.

## Quality (preliminary)
- **Precision: 0 confirmed errors / 400** via-stratified samples (8 paths; LLM-labeled + 64-edge human
  spot-check). **Not yet blind-validated** — treat as preliminary (see docs/METHODOLOGY.md, eval/EVAL_PROTOCOL.md).
  A boundary guard removes compound→generic over-trim collapses (e.g. 失業保険法→保険法).
- **External recall: 68% raw** (measured). In-scope substantive recall is **not yet reliably measured**:
  provisional LLM reads are unstable (78% at n=32 vs 93% at n=103), which is itself why a human-labeled
  gold is required. Misses ≈ extraction artifacts/co-references + out-of-scope (repealed/treaty/foreign).
- **Edge counts**: 1,212,708 external edges (722,426 cross-law + 490,282 self/version) · 55,651 law→law pairs.
- See repo README "Honest limitations" and docs/METHODOLOGY.md.

## Known limitations / biases
- **Current-version collapse**: ~22% of edges are version-bound (旧法/改正前) and map to the *current* version.
- **Lower bound, not exhaustive**: high precision, partial recall — trust what's present; absence ≠ "no citation".
- National scope only (no 条例/case law).

## License
Data: CC-BY-4.0 (attribute e-Gov + this repo). Code: Apache-2.0.
