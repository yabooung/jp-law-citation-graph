# Data Card — JLaw-CiteGraph v2.5

## Source
- **e-Gov 法令検索** (https://laws.e-gov.go.jp/), official Japanese government law database (Digital Agency).
  Bulk download `all_xml.zip`, law list timestamp **<!--v:snapshot-->2026-09-27<!--/v-->**.
- **As-of date <!--v:as_of-->2026-09-29<!--/v-->.** Each law is taken at the version in force on that date. Versions with a
  later 施行日 are listed in `pending_versions.csv`.
- Japanese statutes are not subject to copyright (Copyright Act Art. 13). e-Gov law data is provided
  for reuse with source attribution.
- `eval/v2/nta_gold.jsonl` is derived from the National Tax Agency 質疑応答事例 (国税庁ホームページ,
  edited; attribution required).

## Scope
- **Included:** national statutes in force: 法律 <!--v:type:法律-->2,101<!--/v--> · 政令 <!--v:type:政令-->2,324<!--/v--> · 府省令 <!--v:type:府省令-->4,099<!--/v--> · 規則 <!--v:type:規則-->407<!--/v--> ·
  勅令 <!--v:type:勅令-->66<!--/v--> · 憲法 <!--v:type:憲法-->1<!--/v--> = **<!--v:laws-->8,998<!--/v--> laws** (from <!--v:law_versions-->10,648<!--/v--> e-Gov law versions).
- **Excluded:** local ordinances (条例), case law (判例), 通達, the text of repealed laws and of
  amending acts (一部改正法), and treaties as nodes. Citations *to* these exist in the text but have
  no target node.

## Graph (full build)
| Nodes | count | | Edges | count |
|---|---:|---|---|---:|
| Law | <!--v:nodes.laws-->8,998<!--/v--> | | CONTAINS (tree) | <!--v:contains-->1,877,998<!--/v--> |
| Hierarchy (編章節款目) | <!--v:nodes.hierarchy-->26,664<!--/v--> | | CITES | <!--v:cites-->1,418,223<!--/v--> |
| Article | <!--v:nodes.articles-->243,277<!--/v--> | | DELEGATES_TO (政令で定める → law) | <!--v:delegates-->67,666<!--/v--> |
| Paragraph | <!--v:nodes.paragraphs-->504,241<!--/v--> | | REFERS_TO_ATTACHMENT | <!--v:attachment_refs-->37,377<!--/v--> |
| Item | <!--v:nodes.items-->515,834<!--/v--> | | AMENDS | <!--v:amends-->117<!--/v--> |
| 附則 article / paragraph | <!--v:nodes.suppl_articles-->240,053<!--/v--> / <!--v:nodes.suppl_paragraphs-->326,379<!--/v--> | | | |
| Attachment (別表・様式…) | <!--v:nodes.attachments-->21,550<!--/v--> | | | |

Node ids are stable and readable: `129AC0000000089_a709` (民法第七百九条), `…_a10-2_p3_i12-2`
(第十条の二第三項第十二号の二), `…_asup-sp1-2` (附則第二条), `…_at-style-1` (様式第一).
Article-less provisions sit under a synthetic article `0`.

## Released files (`/data`)
| File | Rows | Notes |
|---|---:|---|
| `laws.csv` | <!--v:laws-->8,998<!--/v--> | v1 columns + `enforcement_date`, `next_enforcement_date`, `pending_versions` |
| `cites_edges.jsonl.gz` | <!--v:ext_edges-->622,586<!--/v--> | citations of a named law (<!--v:ext_cross-->527,879<!--/v--> to another law, <!--v:ext_self-->94,707<!--/v--> to the law's own amended version such as 新法), article-level, v1 fields + node ids |
| `cites_law_to_law.csv` | <!--v:pairs-->70,600<!--/v--> | distinct src_law → tgt_law pairs with counts |
| `cites_all_edges.jsonl.gz` | <!--v:all_edges-->1,523,383<!--/v--> | every CITES / DELEGATES_TO / REFERS_TO_ATTACHMENT / AMENDS edge |
| `pending_versions.csv` | <!--v:pending-->1,649<!--/v--> | upcoming amendments (<!--v:pending_laws-->841<!--/v--> laws) |

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
`version: "pre_amendment"` and confidence ≤ 0.7: the law is right, but only its current text is in the graph (<!--v:pre_amendment_edges-->13,034<!--/v--> edges).

## Quality
- **Integrity:** 11 validation checks pass: id format, CONTAINS is a tree, no dangling edges,
  body-text floors, deterministic hash.
- **Resolution rates** (targets outside the corpus excluded, reported separately):

  | | resolved / extracted | rate |
  |---|---:|---:|
  | same-law citations | <!--v:res.internal.k-->301,863<!--/v--> / <!--v:res.internal.n-->324,412<!--/v--> | <!--v:res.internal-->93.0%<!--/v--> |
  | cross-law citations | <!--v:res.external.k-->670,243<!--/v--> / <!--v:res.external.n-->815,281<!--/v--> | <!--v:res.external-->82.2%<!--/v--> |
  | relative references | <!--v:res.referential.k-->486,940<!--/v--> / <!--v:res.referential.n-->527,858<!--/v--> | <!--v:res.referential-->92.2%<!--/v--> |

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
