# Changelog

## Unreleased

- **The two `.jsonl.gz` edge files are on Hugging Face only** (`jlawcite download --data DIR`, or the
  dataset's `data/`, tagged per snapshot). Git stores a compressed file in full on every change, so
  committing them monthly added ~28 MB to the history each time; the CSVs and `release_stats.json` stay
  in the repo (they are stored as diffs, a few KB a month). `release_stats.json` gains `article_links`
  and `pre_amendment_edges`, so the docs are rendered without the edge files.
- **`/data` follows the monthly refresh.** After each real Hugging Face publish, the workflow commits
  the same build's `/data`, `eval/v2/nta_retrieval_results.json` and `explorer.html` to `main`, so the
  repo and the latest snapshot tag no longer drift apart (before, `/data` changed only on code releases).
  The regression gate therefore compares each month with the previous published one.
- **Doc numbers are generated.** `tools/render_docs.py` fills every count, rate and date in the READMEs,
  DATA_CARD, DATA_LICENSE, METHODOLOGY and CITATION.cff from `/data` and the benchmark results
  (`<!--v:KEY-->` markers); `tests/test_render_docs.py` fails when a doc is out of date. This corrected
  numbers left over from v3.2: same-law resolution 92.9% → 93.0% (301,863 / 324,412), the cross-law and
  relative-reference counts, citations inside amending-law 附則 295,023 → 294,990, and the
  `pre_amendment` edge count 16,311 → 13,034 (the edges in `/data` that carry `version: "pre_amendment"`;
  16,311 was a pipeline counter). Also the release badge and BibTeX version (2.3.0 → 2.5.0).
- `release_stats.json` adds `nodes` (by type), `resolution` (resolved / extracted), `resolution_excluded`
  and `egov_law_versions`. gzip files are written with a fixed header time, so the same build gives the
  same bytes.

## v2.5.0 — 2026-10-20

- **Extraction fix: articles in parentheses after another law's 編・章・節・款・目.** In
  「行政手続法第二章（申請に対する処分）（第八条（理由の提示）を除く。）」 the 第八条 is 行政手続法's, but it
  was resolved to the citing law's own 第八条. Such a 第N条 (and the 「、」 list that follows it, also after
  「及び第三章（…）（」) now carries the law of the division reference (`extracted_from`
  `INTERNAL_PAT/division_carry`, `via` `division_carry` in `cites_edges`). On the 2026-09-27 snapshot:
  **962 edges added** (284 division_carry, 676 list carry-over, 2 同条) and **387 wrong same-law edges removed**;
  20 random changed edges checked against the text, all correct. Example: laws citing 行政手続法第8条 3 → 7.
- `/data` rebuilt from the same snapshot: CITES 1,417,648 → 1,418,223, citations of another law
  526,919 → 527,879, law→law pairs 70,577 → 70,600; `laws.csv` and `pending_versions.csv` unchanged.
  The retrieval benchmark is unchanged (BM25+graph Recall@10 0.5059).
- Hugging Face snapshots published before this release (2026-09-27 … 2026-10-03) were built with the old
  extraction; the next published snapshot uses the fix.
- Monthly refresh: a **regression gate** (`tools/regression_gate.py`) now runs after the retrieval benchmark and
  stops the publish if the new snapshot is clearly worse than the release in this repo (Recall@10 −0.02,
  citation edges −3%, delegation edges −5%, laws −2%, …; increases never fail). The table goes to the job
  summary; `workflow_dispatch skip_gate=true` overrides once.

## v2.4.1 — 2026-10-09

- The Hugging Face dataset moved to **`yabooung/jp-law-citation-graph`** (account renamed). `jlawcite download`,
  `jlawcite mcp` and `tools/publish_hf.py` now default to the new id. The old id still redirects, so earlier
  versions keep working; set `JLAWCITE_HF_REPO` to override. Data and code are otherwise unchanged.

## v2.4.0 — 2026-10-01

- **Removed `jlawcite.nta_processor` and `jlawcite.citation.parse_kankeihrei`** (the NTA resolver used
  until 2.2). It kept only the first citation of each 関係法令 line and attached 施行令 articles to the
  parent act. Use `jlawcite.pipeline.resolve_gold` (`parse_refs`, `resolve_case`), which has produced
  `eval/v2/nta_gold.jsonl` since 2.3.0. The graph, the search index and the benchmark numbers are unchanged.
- `tools/publish_hf.py` also uploads the NTA gold (`eval/nta_gold.jsonl`, the `nta_retrieval` config;
  `--gold`, default `eval/v2/nta_gold.jsonl`), so the monthly refresh keeps it in sync with the repo.

## v2.3.0 — 2026-09-30

- **NTA benchmark gold rebuilt** (`eval/v2/nta_gold.jsonl`): 質疑応答事例 re-collected on 2026-09-29
  (1,598 cases; 1,186 with article-level answers, was 1,700 / 1,170). NTA ids are not stable (70 ids
  now point to a different question), so queries and answers come from one collection. The new resolver
  reads every article in a 「、」 list (the old one kept only the first per line), attaches 施行令 articles
  to the 施行令 rather than the parent act, and parses full-width 枝番 (「第22条の２」 → a22-2).
  Recall@10 on the 2026-09-27 snapshot: BM25 0.244 → 0.305, BM25+graph 0.459 → 0.506. The old gold
  gives identical numbers on the same DB, so the change comes from the gold alone.
- **`resolve_gold` rewritten** with that resolver. It reads a one-line-per-case JSONL collection and
  reproduces `eval/v2/nta_gold.jsonl` byte for byte from the 2026-09-29 collection. `nta_processor`
  (the old resolver) is no longer used by the pipeline.

## v2.2.0 — 2026-09-29

- **MCP server in the package**: `jlawcite mcp` (extra `[mcp]`). One line for Claude Code:
  `claude mcp add jlawcite -- uvx --from "jlawcite[mcp]" jlawcite mcp`. With no data present it
  downloads the latest snapshot in the background on first start. `mcp/server.py` is now a shim.
- **Lighter download**: the search DB is shipped packed (no chunk table / FTS index, xz):
  **~115 MB instead of ~680 MB**. `jlawcite download` rebuilds the dropped tables locally
  (~1 min; identical chunks and search results) and also saves laws.csv, cites_law_to_law.csv and
  pending_versions.csv next to the DB. Snapshots published before this keep the gzip layout and
  still download.
- `tools/publish_hf.py --force` (and the workflow's `force` input) republishes a snapshot.

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
