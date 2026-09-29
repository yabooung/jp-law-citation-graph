# JLaw-CiteGraph 🇯🇵⚖️

**English** · [日本語](https://github.com/yabooung/jp-law-citation-graph/blob/main/README.ja.md) · [한국어](https://github.com/yabooung/jp-law-citation-graph/blob/main/README.ko.md)

![code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue) ![data: CC BY 4.0](https://img.shields.io/badge/data-CC--BY--4.0-green) ![deterministic](https://img.shields.io/badge/pipeline-deterministic%20·%20no%20LLM-brightgreen) ![version](https://img.shields.io/badge/release-v2.2.0-informative) [![PyPI](https://img.shields.io/pypi/v/jlawcite)](https://pypi.org/project/jlawcite/) [![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97-dataset-yellow)](https://huggingface.co/datasets/dbwjspdlagjdyd/jp-law-citation-graph)

**An open, deterministic citation graph and search index for Japanese statutory law.**

Every Japanese law in force is parsed from official [e-Gov](https://laws.e-gov.go.jp/) XML down
to article (条), paragraph (項) and item (号), and citations in the text are resolved to the provision
they point at: 92.9% of same-law and 82.2% of cross-law citations, with the unresolved ones listed.
The result ships as data files, a single-file explorer, a `jlawcite` command-line tool
that looks up and searches provisions without embeddings, and an MCP server for LLMs.

[![JLaw-CiteGraph interactive explorer](https://raw.githubusercontent.com/yabooung/jp-law-citation-graph/main/assets/explorer-screenshot.png)](https://github.com/yabooung/jp-law-citation-graph/blob/main/explorer.html)

<sub>[`explorer.html`](https://github.com/yabooung/jp-law-citation-graph/blob/main/explorer.html): pick a law and see what it cites (green) and what cites it (yellow).</sub>

## At a glance (v2.0, e-Gov snapshot 2026-09-27)

| | |
|---|---|
| **Laws** | 8,998, each at the version in force on 2026-09-29, plus **1,649 upcoming amendments** (施行日 + amending law) |
| **Graph** | 1.89M nodes (条・項・号・附則・別表) · 1.42M citation edges · 67,666 delegation edges (政令で定める) · 37,377 別表/様式 references |
| **Law → law network** | 70,577 distinct pairs · 453,390 distinct article-level links between laws |
| **Citation resolution** | same-law 92.9% · cross-law 82.2% · relative refs (前条/同項/…) 92.2% |
| **Precision** | ≈98% on hand-checked samples of the rules covering 86% of edges (preliminary, see below) |
| **Search** | `jlawcite get 民法第七百九条` · BM25 search · on 1,170 real tax questions the citation graph lifts Recall@10 from 0.24 to 0.46 |
| **Method** | 100% deterministic (rules + dictionaries + document context), no LLM, reproducible from the public e-Gov bulk download |
| **Updates** | Rebuilt monthly from e-Gov; each snapshot is tagged on Hugging Face (`jlawcite download --list`, `--snapshot YYYY-MM-DD` to pin one) |

## What's new in v2

| | v1.0 (2026-06) | **v2.0 (2026-09)** |
|---|---|---|
| Unit | law → law (article strings) | article / paragraph / item nodes, incl. 附則 and attachments |
| Edges | cross-law citations | + same-law citations, 前条/同項/前号, delegation, 別表 references |
| Distinct article-level cross-law links | 173,844 | **453,390** |
| Law → law pairs | 55,651 | **70,577** |
| Versions | latest file per law | version in force on a date + upcoming amendments |
| Search | – | `jlawcite` CLI (lookup, BM25, graph walk) + retrieval benchmark |
| Precision | 0 errors / 400 (LLM-proposed labels) | per-rule samples with confidence intervals; 5 error classes found and fixed |

v1 wrote one line per citation *mention*, so its 1.21M lines hold 173,844 distinct links; v2 counts
each (source, target) link once. Full list in [CHANGELOG.md](https://github.com/yabooung/jp-law-citation-graph/blob/main/CHANGELOG.md).

## Who is this for?
| You are… | You use it to… |
|---|---|
| a **legal-NLP researcher** | add citation neighbours to statute retrieval / RAG (the benchmark below shows the gain), or reuse the deterministic resolver on your own corpus |
| a **legal-tech developer** | answer "what cites X?" (amending 個人情報保護法 touches **111** laws) and "what changes when?" (`pending_versions.csv`) |
| a **network / comparative-law researcher** | study hubs (地方自治法 is cited by 1,250 laws), delegation chains and dependency clusters |
| building an **LLM legal assistant** | ground citations deterministically via the MCP server: `会社法第737条` → the exact article text |

## Quick start
```bash
pip install jlawcite                                 # CLI + library from PyPI
jlawcite download                                    # prebuilt search DB (~115 MB download, ~1 min to unpack)
jlawcite get 民法第七百九条

# or, to rebuild the graph:
git clone https://github.com/yabooung/jp-law-citation-graph && cd jp-law-citation-graph
pip install -e .                                     # Python 3.11+

jlawcite fetch                                       # e-Gov bulk XML (~320 MB) → data/raw/law_xml
jlawcite build --input data/raw/law_xml \
    --csv data/raw/law_xml/all_law_list.csv --output data/parsed      # ~5 min, deterministic
jlawcite validate --data data/parsed                 # 11 integrity checks
jlawcite index                                       # search index (~1.5 min, 2.6 GB)

jlawcite get 民法第七百九条                           # also: 労働基準法20条1項, 激甚法第三条, node ids
jlawcite search 解雇 予告                             # BM25; --nl for a question sentence
jlawcite refs 労働基準法第二十条                       # what it cites / what cites it
jlawcite pending --until 20261231                    # amendments coming into force
```

```text
$ jlawcite get 民法第七百九条
民法  [129AC0000000089, act, 明治二十九年法律第八十九号]  現行 2026-06-24 施行中, 次回改正 2027-06-23
[129AC0000000089_a709] Article

第七百九条
故意又は過失によって他人の権利又は法律上保護される利益を侵害した者は、これによって生じた損害を賠償する責任を負う。

改正予定:
  2027-06-23  民法 ← 民法等の一部を改正する法律 令和八年法律第四十五号 (公布の日から起算して一年を超えない範囲内において政令で定める日)
  …
```

Every command takes `--json`. The same functions are available in Python (`jlawcite.search.SearchDB`).

## What's inside (`/data`)
| File | Content |
|---|---|
| `laws.csv` | `law_id, name, type, url` (v1) + `enforcement_date, next_enforcement_date, pending_versions` |
| `cites_law_to_law.csv` | aggregated `src_law → tgt_law` counts (v1 columns) |
| `cites_edges.jsonl.gz` | every resolved citation of a named law: v1 fields (`src_article`, `tgt_article`, `via`, `confidence`) + `src_node`, `tgt_node`, `fallback_level` |
| `cites_all_edges.jsonl.gz` | **every** edge of the graph: CITES (incl. same-law and 前条/同項), DELEGATES_TO, REFERS_TO_ATTACHMENT, AMENDS, each with `extracted_from` |
| `pending_versions.csv` | upcoming amendments: 施行日, 施行日備考, amending law, e-Gov URL |
| `release_stats.json` | the counts quoted here |

The full node file (1.89M nodes, article and paragraph text included) is attached to the GitHub
release, or you can rebuild it with the Quick start commands.

```python
import pandas as pd
edges = pd.read_csv("data/cites_law_to_law.csv")
hubs = edges.groupby("tgt_law")["src_law_id"].nunique().sort_values(ascending=False).head(10)
```

## Use it from an LLM: MCP server
One line for Claude Code (needs [uv](https://docs.astral.sh/uv/); data is downloaded on first start):
```bash
claude mcp add jlawcite -- uvx --from "jlawcite[mcp]" jlawcite mcp
```
Tools: `resolve_citation`, `what_cites`, `what_law_cites`, `citation_path`, `get_law`,
`get_provision` (citation → text), `search_statutes` and `pending_amendments`.
See [`mcp/README.md`](https://github.com/yabooung/jp-law-citation-graph/blob/main/mcp/README.md).

## Retrieval benchmark
Each of 1,170 National Tax Agency Q&A cases (質疑応答事例) is a real tax question whose answer cites
specific articles. The question is the query, and hits are counted at the article level
(`jlawcite eval`).

| method | R@1 | R@5 | R@10 | R@20 | R@50 | MRR@50 | s/query |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 (character-trigram OR) | 0.086 | 0.192 | 0.244 | 0.326 | 0.437 | 0.140 | 0.11 |
| BM25 + 1-hop citation graph | **0.256** | **0.403** | **0.459** | **0.500** | **0.550** | **0.325** | 0.11 |

<sub>1,170 queries · e-Gov snapshot 2026-09-27 · `eval/v2/nta_retrieval_results.json`</sub>

The one-hop expansion adds the articles that the top hits cite. A retrieved 施行令 paragraph pulls
up the parent-act article it implements. Both rows use no embeddings; they are a baseline for dense
or hybrid retrievers.

## Quality, honestly
- **Coverage.** No law is left without body text, the 11 integrity checks pass (no dangling edges),
  and the same input produces the same output.
- **Resolution rates** leave out citations whose target is not in a current-law corpus: pre-amendment
  text (旧法), amending acts (改正法), and citations inside amending-law 附則 blocks. These are counted
  separately in `jp_cites_stats.json`.
- **Precision is preliminary.** 180 random edges (10–20 per resolution rule) were checked by hand
  against their source text during development. Five error classes turned up and were fixed. The rules covering 86% of edges now
  measure ≈98%. Samples are small (10/10 still has a 72% lower bound) and were not blind, so treat it
  as indicative. Citations inside amending-law 附則 are about 40% right and are flagged with
  confidence 0.4. Citations of pre-amendment text (「旧○○法第N条」) point at the current version and
  carry `version: "pre_amendment"`. Details: [docs/METHODOLOGY.md](https://github.com/yabooung/jp-law-citation-graph/blob/main/docs/METHODOLOGY.md).
- **Scope.** National statutes in force only: no case law, 通達, local ordinances, or text of repealed
  and amending acts. イ/ロ/ハ subitems are folded into their item.

## Reproduce
```bash
jlawcite fetch --zip all_xml.zip       # re-extract an archived snapshot for an exact rebuild
jlawcite build … --as-of 20260929      # same snapshot + same as-of date → same graph
jlawcite export --out data             # regenerate the files in /data
python tools/build_explorer.py         # regenerate explorer.html
python -m pytest                       # 177 tests
```

## Related work
- **弁護士ドットコム (DDS 2026)** built a citation graph over e-Gov statutes (条・項・号) together with
  books, guidelines and court decisions. It reports P 98.8 / R 92.1 for law-to-law citations; same-law
  references are outside its evaluation, and the graph is not public.
  [paper](https://dbsj.org/wp-content/uploads/2025/11/dds-vol4-no3.pdf)
- **[DaisukeHori/japan-law](https://github.com/DaisukeHori/japan-law)** publishes about 112k article-level
  cross-references for about 8,000 laws (CC0), without an accuracy evaluation.
- Reference resolution in Japanese statutes goes back to Tran, Nguyen & Shimazu (ICAIL 2013). Using
  citation structure for statute retrieval has been shown on the Japanese Civil Code (Mizuno & Kano,
  COLIEE 2025; Vuong et al., *Applied Intelligence* 2025) and on Belgian law (Louis et al., EACL 2023).

JLaw-CiteGraph adds same-law and relative references (前条・同条・同項・前号・同法), version selection with
upcoming amendments, per-rule precision, and a retrieval evaluation over the whole corpus, all as open data.

## Documentation
[CHANGELOG](https://github.com/yabooung/jp-law-citation-graph/blob/main/CHANGELOG.md) · [DATA_CARD](https://github.com/yabooung/jp-law-citation-graph/blob/main/DATA_CARD.md) · [METHODOLOGY](https://github.com/yabooung/jp-law-citation-graph/blob/main/docs/METHODOLOGY.md) ·
[eval protocol](https://github.com/yabooung/jp-law-citation-graph/blob/main/eval/EVAL_PROTOCOL.md) · detailed Korean docs: [dataset](https://github.com/yabooung/jp-law-citation-graph/blob/main/docs/ko/DATASET.md),
[schema & resolution rules](https://github.com/yabooung/jp-law-citation-graph/blob/main/docs/ko/GRAPH_SCHEMA.md), [search](https://github.com/yabooung/jp-law-citation-graph/blob/main/docs/ko/SEARCH.md),
[improvement handbook](https://github.com/yabooung/jp-law-citation-graph/blob/main/docs/ko/IMPROVING_THE_GRAPH.md)

## Contributing
Issues and PRs are welcome: [CONTRIBUTING.md](https://github.com/yabooung/jp-law-citation-graph/blob/main/CONTRIBUTING.md). A blind annotation round
(`eval/`) would turn the preliminary precision into a validated number, and it is the most useful
single contribution.

## License
Code: Apache-2.0. Data: CC BY 4.0 (source: e-Gov 法令データ; NTA 質疑応答事例 for `eval/v2/nta_gold.jsonl`).
See [DATA_LICENSE.md](https://github.com/yabooung/jp-law-citation-graph/blob/main/DATA_LICENSE.md). This is not legal advice; check e-Gov / 官報 for legal decisions.

## Citation
```bibtex
@misc{jlaw_citegraph_2026,
  title   = {JLaw-CiteGraph: An open citation graph of Japanese statutory law},
  version = {2.2.0},
  year    = {2026},
  note    = {e-Gov 2026-09-27 snapshot},
  url     = {https://github.com/yabooung/jp-law-citation-graph}
}
```
