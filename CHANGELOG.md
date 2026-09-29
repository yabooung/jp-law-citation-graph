# Changelog

## v2.1.0 — 2026-09-29

- **`jlawcite download`** fetches the prebuilt search DB (gzip, ~680 MB; sha256-checked) from the
  Hugging Face dataset into `~/.cache/jlawcite/`, so `pip install jlawcite` works without a local
  build. `--snapshot YYYY-MM-DD` pins a snapshot, `--list` shows them, `--data DIR` adds the release files.
- **Monthly refresh.** A scheduled workflow rebuilds from the latest e-Gov bulk download, validates,
  and publishes data, index and benchmark results to Hugging Face, tagged with the e-Gov snapshot date.
  The data files in this git repo change only with code releases.
- The default search DB is `$JLAWCITE_DB`, else `data/search/jp_search.sqlite`, else the download cache.

## v2.0.0 — 2026-09-29 (e-Gov snapshot 2026-09-27)

v2 replaces the v1 pipeline with a structure-level graph builder, adds an embedding-free
search index and a retrieval benchmark, and measures precision per resolution rule.

### Data
- **Snapshot** e-Gov 2026-09-27 (10,648 law versions → 8,998 laws). Each law is taken at the
  version **in force on the as-of date** (2026-09-29). The 1,649 upcoming amendments (841 laws)
  are listed in `data/pending_versions.csv`, and `laws.csv` gains `enforcement_date`,
  `next_enforcement_date` and `pending_versions`.
- **Structure-level graph.** The full build has 1.89M nodes: Law, Hierarchy, Article, Paragraph,
  Item, 附則 articles and paragraphs, and Attachment. Its edges are CITES (incl. same-law
  references and 前条/同項/前号 …), DELEGATES_TO, REFERS_TO_ATTACHMENT and AMENDS.
  `data/cites_all_edges.jsonl.gz` ships every edge; the node file is a release asset.
- **`cites_edges.jsonl.gz` keeps the v1 fields** and adds `src_node`, `tgt_node`, `src_section`,
  `fallback_level`. **Counting changed:** v1 wrote one line per citation *mention*, so the same
  article pair repeated. Its 1,212,708 lines are 173,844 distinct (src law, src article,
  tgt law, tgt article) links. v2 writes one edge per (source node, target node): 621,623 edges,
  453,390 distinct article-level links (**×2.6** over v1).
- **Law→law pairs** 55,651 → **70,577**. Hubs: 地方自治法 cited by 1,250 laws (v1: 1,220),
  個人情報保護法 by 111 (v1: 110).

### Pipeline fixes that change the data
- Article-less 本則 / 附則 (paragraphs directly under the provision) were dropped. 865 laws had no
  body text and about 60% of 附則 blocks were lost. They now sit under a synthetic article `0`.
- Branch numbers (第一章の二, 第十二号の二) collided with their base number and dropped whole
  subtrees; they are kept as `1-2` / `12-2`.
- Inline markup (Ruby, Sup, Sub, ArithFormula, QuoteStruct) truncated about 54k sentences
  (about 1.4M characters). Full text is now kept, and ruby readings are dropped.
- Attachments get kind-aware ids (`at-1` 別表, `at-style-1` 様式, …), kanji and full-width
  numbers are read, and 21,550 attachments are kept (2,483 before).

### Resolution
- Bare 法/令 and 同法/新法/旧法 tokens are handled outside the law-name pattern. In v1, 「法第十条」 in
  a 施行令 could land on the 施行令's own 第十条.
- Per-law abbreviation definitions (以下「法」という。, 16.8k) and official short names
  (LawTitle@Abbrev, 3.2k) are used.
- Enumeration carryover (「会社法第十条、第十一条」), scoped 本則 / 附則 lookup, 同条/同項/同号 bound
  to the preceding citation, and 前号/次号/前各号 are added.
- The v1 boundary guard (no 失業保険法 → 保険法 collapse) and the mined standard abbreviations
  are carried over.
- Citations naming pre-amendment text (「旧○○法」「改正前の○○法」) keep their edge to the current
  law but carry `version: "pre_amendment"` and confidence ≤ 0.7 (16,311 edges).
- Citations inside amending-law 附則 blocks are flagged (`INTERNAL_PAT/amend_suppl`,
  confidence 0.4) and kept out of the KPIs.

### New
- `jlawcite` CLI: `fetch`, `build`, `validate`, `export`, `index`, `search`, `get`, `refs`, `law`,
  `pending`, `eval`.
- Search index (SQLite FTS5 trigram): `jlawcite get 民法第七百九条`, BM25 keyword and
  natural-language search, and citation-graph navigation.
- Retrieval benchmark on 1,170 NTA 質疑応答事例 questions (`eval/v2/`).
- MCP server: `pending_amendments`, `get_provision` and `search_statutes` are added.
- Precision measured per resolution rule (180 hand-checked edges); see `docs/METHODOLOGY.md`.
- 177 tests, including an end-to-end two-law mini corpus.

### Compatibility
- `laws.csv`, `cites_law_to_law.csv` and `cites_edges.jsonl.gz` keep their v1 columns. New columns
  are appended.
- `from jlawcite import citation, resolver, parser` still works. `src/build_graph.py`,
  `src/fetch_egov.py` and `src/mine_abbreviations.py` are replaced by `jlawcite fetch` /
  `jlawcite build`. The mined abbreviations are merged into `src/jlawcite/jp_law_aliases.json`.
- The core now needs `pydantic` and `tqdm` (`pip install -e .`). v1 was standard-library only.

## v1.0.0 — 2026-06-26 (e-Gov snapshot 2026-06-23)
First release: the law→law external citation graph (8,980 laws), the `jlawcite` resolver,
explorer, MCP server and evaluation protocol.
