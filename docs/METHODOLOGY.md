# How JLaw-CiteGraph is built (v2)

The pipeline, the resolution rules and the quality picture. For using the data see the
[README](../README.md); for the schema see the [DATA_CARD](../DATA_CARD.md). Every rule, with
examples, is in the Korean spec [docs/ko/GRAPH_SCHEMA.md](ko/GRAPH_SCHEMA.md) §4.

## Pipeline

```
e-Gov all_xml.zip ─ jlawcite fetch ─▶ {law_id}_{施行日}_{改正ID}/*.xml + all_law_list.csv
   ─ jlawcite build --as-of D ─▶ pick the version in force on D per law (later ones → pending)
      Pass 1   XML → nodes + CONTAINS tree
      Pass 1.5 name resources: titles, 法令番号, 旧法令名, official short names (LawTitle@Abbrev),
               curated + mined aliases, per-law definitions (以下「X」という。), 法–施行令–施行規則 family
      Pass 2   per text node: extract citations → resolve → CITES / DELEGATES_TO / REFERS_TO_ATTACHMENT / AMENDS
   ─ jlawcite validate (11 checks) ─ jlawcite export / index / eval
```

Deterministic: no LLM, no randomness. Same snapshot + same as-of date + same code → same graph.

## Parsing
- Nodes: Law, Hierarchy (編章節款目), Article, Paragraph, Item, 附則 article/paragraph, Attachment.
- **Article-less provisions** (paragraphs placed directly under 本則 or 附則) go under a synthetic
  article `0`. Without it, 865 laws had no body text and most 附則 blocks were lost.
- **Branch numbers** (第一章の二, 第十二号の二) keep their full path (`1-2`, `12-2`); truncating them
  made siblings collide and dropped whole chapters.
- **Full text** includes inline markup (Ruby, Sup, Sub, ArithFormula, QuoteStruct); ruby readings
  are removed.
- Each 附則 block is its own scope (`sp{i}`); the first block without `AmendLawNum` is the enactment
  附則. Attachments get kind-aware ids.

## Extraction
- Named law + locator: `法令名（法令番号。以下「X」という。）附則第N条の二第M項第K号の三`.
- Short tokens outside the name pattern: bare `法`/`令` (the parent act or order, from inside a
  施行令/施行規則), `同法`/`同令`, `新法`/`旧法`. Only a non-kanji character may precede them, so 「税法第」
  is not split.
- Same-law `第N条` and `附則第N条` / `附則第N項`, attachment refs (`別表第二`, `様式第三号`,
  bare `別表`), delegation (`政令で定める`), and relative references (`前条`, `同項`, `前号`,
  `前各号`, with trailing locators such as `同条第二項`).
- An over-captured clause in front of a law name is trimmed from the reference span, so any
  `前項` or `第N条` inside it is still extracted.

## Resolution
1. **Per-law definitions first.** `水先法（…。以下「法」という。）` makes `法` mean 水先法 in that law.
   Definitions of pre-amendment text (`改正前の…`, `旧…`) or of amending acts are marked out of scope.
2. **Short tokens.** `同法` → latest cited *Act*; `同令` → latest cited order/ordinance. `新法` → the law
   itself when the kinds match. `旧法` → out of scope. Bare `法`/`令` → the parent act or sibling order.
3. **Name index.** 法令番号 → exact title → 旧法令名 → alias / official short name → strip
   `新`/`旧`/`改正前の` → trim over-grab → trailing match. Trimming and trailing match cut only at a
   clause, particle or version boundary, never inside a compound name (so 失業保険法 does not become
   保険法).
4. **Enumeration carryover.** `会社法第八百三十三条第二項、第八百三十四条` and
   `第百八十五条から第百八十七条まで` keep the first law and its 附則 scope when only connectors,
   parentheses or `第N項` stand between the parts.
5. **Relative references.** `同条` → the last *article* cited in the text (or the source article if
   none); `同項`/`同号` likewise. `前条`/`次条` must be numerically adjacent (excerpted 附則 skip
   articles). `前号`/`前各号` use the item list.
6. **Scopes.** Lookups never mix 本則 and 附則. Citations inside amending-law 附則 blocks are
   flagged `INTERNAL_PAT/amend_suppl` (confidence 0.4) and excluded from the KPIs.

## Quality

### Resolution rates
The numerators and denominators are in `jp_cites_stats.json`. Excluded from the denominators:
- 旧法 / 改正前 references: 25,345
- 改正法 references: 44,184
- citations inside amending-law 附則: 295,023
- self and modifier tokens (本条, 各号): 123,160

| | rate |
|---|---:|
| same-law | 92.9% |
| cross-law | 82.2% |
| relative | 92.2% |

### Precision (preliminary)
Edges were drawn at random per resolution rule and checked against the source text and the target
provision during development. The check was not blind. Rules with errors were fixed and then
re-sampled.

| rule | edges | sample correct | precision (95% Wilson) |
|---|---:|---:|---|
| `INTERNAL_PAT` | 309,325 | 20/20 | 100% (84–100) |
| `NAKED_LAW_PAT/defined_abbrev` | 200,120 | 10/10 | 100% (72–100) |
| `EXTERNAL_FULL_PAT/canonical` | 140,552 | 20/20 ¹ | 100% (84–100) |
| `REFERENTIAL/前項` | 112,188 | 10/10 | 100% (72–100) |
| `INTERNAL_PAT/enum_carryover` | 89,847 | 10/10 | 100% (72–100) |
| `REFERENTIAL/同条` | 62,858 | 17/20 | 85% (64–95) |
| `NAKED_LAW_PAT/same_as_last` | 61,144 | 19/20 | 95% (76–99) |
| `EXTERNAL_FULL_PAT/promulgation` | 55,857 | 10/10 | 100% (72–100) |
| `EXTERNAL_FULL_PAT/defined_abbrev` | 46,313 | 10/10 | 100% (72–100) |
| `REFERENTIAL/前各号` | 45,808 | 10/10 | 100% (72–100) |
| `REFERENTIAL/前条` | 44,687 | 20/20 | 100% (84–100) |
| `REFERENTIAL/同項` | 33,108 | 9/10 | 90% (60–98) |
| `EXTERNAL_FULL_PAT/prefix_stripped` | 17,713 | 20/20 ¹ | 100% (84–100) |
| `INTERNAL_PAT/amend_suppl` | 106,323 | 4/10 | 40% (17–69) — excluded from KPIs, confidence 0.4 |

¹ Right law in all 20; 3 (canonical) and 5 (prefix_stripped) cite the pre-amendment text (「旧○○法」「改正前の○○法」). Those 16,311 edges carry `version: "pre_amendment"` and confidence 0.7 because only the current version is in the graph.

Weighted by edge count, the sampled rules (86% of CITES) come to about 98%. With 10–20 edges per
rule, one rule's interval is wide: 10/10 still bounds the rate only above 72%. The error classes
found and fixed were:
- `同条` taking `前項` as its antecedent
- `前条` jumping over missing articles in excerpted 附則
- joint-ministry 法令番号 (運輸省・建設省令) not parsed
- titles ending in `…に関する省令` cut to a bare token
- `同法` pointing at a cabinet order

Remaining error types:
- article numbers inside 読み替え quotations (`…中「第X条」とあるのは…`)
- `同条` after a reference to an amending act

The blind, multi-annotator protocol in [eval/EVAL_PROTOCOL.md](../eval/EVAL_PROTOCOL.md) is the way to
turn these into validated figures.

### Retrieval
See the README benchmark. On 1,186 NTA questions the citation graph raises Recall@10 from 0.31 to 0.51 over a
character-trigram BM25 baseline, with no embeddings.

## Limitations
- Current law only. Upcoming amendments are metadata (date, amending law), not future text.
- No node for repealed laws, amending acts, treaties, case law, 通達 or local ordinances.
- Subitems (イ・ロ・ハ) are folded into their item. Tables keep text only.
- DELEGATES_TO targets the delegated-to law, not an article.
- Precision figures are preliminary (small, non-blind samples).
