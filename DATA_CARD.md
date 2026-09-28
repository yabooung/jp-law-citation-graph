# Data Card — JLaw-CiteGraph v2.0

## Source
- **e-Gov 法令検索** (https://laws.e-gov.go.jp/), official Japanese government law database (Digital Agency).
  Bulk download `all_xml.zip`, law list timestamp **2026-09-27**.
- **As-of date 2026-09-29.** Each law is taken at the version in force on that date. Versions with a
  later 施行日 are listed in `pending_versions.csv`.
- Japanese statutes are not subject to copyright (Copyright Act Art. 13). e-Gov law data is provided
  for reuse with source attribution.
- `eval/v2/nta_gold.jsonl` is derived from the National Tax Agency 質疑応答事例 (国税庁ホームページ,
  edited; attribution required).

## Scope
- **Included:** national statutes in force: 法律 2,101 · 政令 2,324 · 府省令 4,099 · 規則 407 ·
  勅令 66 · 憲法 1 = **8,998 laws** (from 10,648 e-Gov law versions).
- **Excluded:** local ordinances (条例), case law (判例), 通達, the text of repealed laws and of
  amending acts (一部改正法), and treaties as nodes. Citations *to* these exist in the text but have
  no target node.

## Graph (full build)
| Nodes | count | | Edges | count |
|---|---:|---|---|---:|
| Law | 8,998 | | CONTAINS (tree) | 1,877,998 |
| Hierarchy (編章節款目) | 26,664 | | CITES | 1,417,648 |
| Article | 243,277 | | DELEGATES_TO (政令で定める → law) | 67,666 |
| Paragraph | 504,241 | | REFERS_TO_ATTACHMENT | 37,377 |
| Item | 515,834 | | AMENDS | 117 |
| 附則 article / paragraph | 240,053 / 326,379 | | | |
| Attachment (別表・様式…) | 21,550 | | | |

Node ids are stable and readable: `129AC0000000089_a709` (民法第七百九条), `…_a10-2_p3_i12-2`
(第十条の二第三項第十二号の二), `…_asup-sp1-2` (附則第二条), `…_at-style-1` (様式第一).
Article-less provisions sit under a synthetic article `0`.

## Released files (`/data`)
| File | Rows | Notes |
|---|---:|---|
| `laws.csv` | 8,998 | v1 columns + `enforcement_date`, `next_enforcement_date`, `pending_versions` |
| `cites_edges.jsonl.gz` | 621,623 | citations of a named law (526,919 to another law, 94,704 to the law's own amended version such as 新法), article-level, v1 fields + node ids |
| `cites_law_to_law.csv` | 70,577 | distinct src_law → tgt_law pairs with counts |
| `cites_all_edges.jsonl.gz` | 1,522,808 | every CITES / DELEGATES_TO / REFERS_TO_ATTACHMENT / AMENDS edge |
| `pending_versions.csv` | 1,649 | upcoming amendments (841 laws) |

Counting: one edge per (source node, target node). v1 counted mentions (see CHANGELOG).

### `extracted_from` / `via` — how an edge was resolved
| value | meaning |
|---|---|
| `canonical`, `promulgation`, `old_name`, `alias`, `prefix_stripped`, `suffix` | law named in the text, matched by exact title, 法令番号, 旧法令名, curated/official abbreviation, after stripping 新/旧, or by trailing match at a clause boundary |
| `defined_abbrev` | abbreviation defined in the same law: `水先法（…。以下「法」という。）` |
| `same_as_last` | 同法 / 同令: the latest cited law of that kind |
| `anaphora_family`, `amended_self` | bare 法/令 in a 施行令/施行規則 → parent act / sibling; 新法 → the law itself |
| `enum_carryover` | enumeration: `会社法第十条、第十一条` → both in 会社法 |
| `INTERNAL_PAT` | same-law `第N条` |
| `REFERENTIAL/前条`, `…/同項`, `…/前号`, … | relative references |
| `INTERNAL_PAT/amend_suppl` | `第N条` inside an amending law's 附則 (**low confidence 0.4**) |

Edges whose citation names the pre-amendment text (「旧○○法第N条」, 「改正前の○○法」) carry
`version: "pre_amendment"` and confidence ≤ 0.7: the law is right, but only its current text is in the graph (16,311 edges).

## Quality
- **Integrity:** 11 validation checks pass: id format, CONTAINS is a tree, no dangling edges,
  body-text floors, deterministic hash.
- **Resolution rates** (targets outside the corpus excluded, reported separately):

  | | resolved / extracted | rate |
  |---|---:|---:|
  | same-law citations | 302,262 / 325,347 | 92.9% |
  | cross-law citations | 669,275 / 814,313 | 82.2% |
  | relative references | 486,932 / 527,858 | 92.2% |

- **Precision (preliminary):** see [docs/METHODOLOGY.md](docs/METHODOLOGY.md). About 98% across the
  rules that carry 86% of the edges, from small hand-checked samples that were not blind.

## Known limitations / biases
- Current law only; `pending_versions.csv` gives dates and amending laws, not the future text.
- Citations to repealed or amending acts, treaties, case law and 通達 have no target.
- Subitems (イ・ロ・ハ) are folded into their item; tables keep text but not structure.
- Citation density is highest in tax, finance and company law, and the retrieval benchmark is tax-only.
- DELEGATES_TO links to the delegated-to law, not to a specific article.

## License
Data: CC BY 4.0 (attribute e-Gov and this repo; NTA for `eval/v2/nta_gold.jsonl`). Code: Apache-2.0.
