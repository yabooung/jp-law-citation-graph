# JLaw-CiteGraph 🇯🇵⚖️

**English** · [日本語](README.ja.md) · [한국어](README.ko.md)

![code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue) ![data: CC BY 4.0](https://img.shields.io/badge/data-CC--BY--4.0-green) ![deterministic](https://img.shields.io/badge/pipeline-deterministic%20·%20no%20LLM-brightgreen)

**The first open, deterministically-resolved citation graph of Japanese statutory law.**

A reproducible graph of how Japan's national laws cite each other — extracted deterministically
from official [e-Gov](https://laws.e-gov.go.jp/) law XML, with every edge resolved to a specific
law/article. Precision is checked on stratified samples (preliminary — see limitations).

[![JLaw-CiteGraph interactive explorer](assets/explorer-screenshot.png)](explorer.html)

<sub>The single-file **[`explorer.html`](explorer.html)** — pick a law, see what it cites (green) and what
cites it (yellow). Shown: 地方自治法 (Local Autonomy Act), the most-cited law (1,220 citing laws).</sub>

> **Ships with:** the graph (CSV/JSONL) · a single-file interactive **explorer** (`explorer.html`) ·
> a reusable deterministic Python resolver (`jlawcite`) · and an **🔌 MCP server** so LLMs (Claude, …)
> can query the citation graph directly — [`mcp/`](mcp/README.md).

| | |
|---|---|
| **Laws (nodes)** | 8,980 distinct laws (from 10,229 e-Gov XML files, 2026-06-23 snapshot) |
| **Resolved external edges** | **1,212,708** article-level — **722,426 cross-law** (law A→law B) + 490,282 self/version refs (新法/旧法 in a law's own 附則) · **55,651 distinct law→law pairs** |
| **Internal (intra-law) edges** | ~3.6M extracted (this release ships the **external** law→law graph) |
| **Edge precision** | *Preliminary.* Checked on a 400-edge path-stratified sample (no confirmed errors so far) — **but not yet blind-validated**, so treat it as indicative, not a verified precision figure. ([help validate →](#contributing) · [method](docs/METHODOLOGY.md)) |
| **External resolution (recall)** | **68% raw** · ~85–90% on in-scope substantive citations *(small-sample estimate)* |
| **Method** | 100% deterministic (regex + dictionary + rule-based resolution) — *no LLM, no randomness, fully reproducible & auditable* |

> ⚠️ **Read this first:** the graph is a high-precision **lower bound**, *not* a complete citation index. Raw recall is ~68% — **a missing edge does not mean "no citation."** Please don't rely on it as an exhaustive or authoritative source (see [Honest limitations](#honest-limitations)).

> Why this matters: e-Gov gives you the law *text*, but not a resolved *citation network*. Building
> one means solving abbreviations (`金商法`→`金融商品取引法`), in-law anaphora (`旧法`/`新法`/`同法`),
> over-grab, and renamed laws (`旧法令名`). This repo does that, deterministically, and ships the graph.

---

> **Release = a dated snapshot.** `v1` is the **e-Gov 2026-06-23** snapshot — a fixed, citable,
> reproducible point in time (the right shape for research). To get a *current* graph, regenerate
> with `src/fetch_egov.py`; you don't depend on this repo being kept up to date.

## Who is this for?
| You are… | You use it to… |
|---|---|
| a **legal-NLP researcher** | augment statute retrieval / RAG with citation neighbors; or use `jlawcite` to resolve citations in your own corpus (e.g. COLIEE statute task) |
| a **legal-tech developer** | answer "what laws reference X?" — e.g. amending 個人情報保護法 surfaces **110** dependent laws to review (a verified lower bound) |
| a **comp-law / network researcher** | study legal structure: hubs (地方自治法 is cited by 1,220 laws), centrality, dependency clusters (load into NetworkX/Neo4j) |
| building an **LLM legal assistant** | ground citations deterministically — resolve `会社法第737条` → a specific law/article, no hallucination |
| **curious** | open `explorer.html` and click through how Japan's laws connect |

## What's inside (`/data`)
- **`laws.csv`** — nodes: `law_id, name, type, url`
- **`cites_law_to_law.csv`** — aggregated edges: `src_law_id, src_law, tgt_law_id, tgt_law, n_citations` (great for network analysis)
- **`cites_edges.jsonl.gz`** — full edges: `src_law/src_article → tgt_law/tgt_article`, with `via` (how it resolved) + `confidence`

Every edge carries a `via` ∈ {`canonical`, `promulgation`, `alias`, `old_name`, `prefix_stripped`,
`suffix`, `local_def`, `local_def_tail`} and a `confidence`, so you can filter to a high-confidence subset.

## Quick look (computed from the graph)
**Most-cited laws (hubs)** — how many *other* laws cite them:
| Law | Cited by |
|---|---|
| 地方自治法 (Local Autonomy Act) | 1,220 |
| 会社法 (Companies Act) | 629 |
| 児童福祉法 (Child Welfare Act) | 500 |
| 行政手続法 (Admin. Procedure Act) | 462 |
| 民法 (Civil Code) | 411 |

**Impact analysis** — "what cites X?" → a verified lower bound:
`個人情報保護法` (Personal Information Protection Act) ← **110 laws**.

## Use it
```python
import pandas as pd
laws  = pd.read_csv("data/laws.csv")
edges = pd.read_csv("data/cites_law_to_law.csv")

# top hub laws
hubs = edges.groupby(["tgt_law_id","tgt_law"])["src_law_id"].nunique() \
            .sort_values(ascending=False).head(20)

# impact set: what cites a given law?
target = laws[laws.name=="個人情報の保護に関する法律"].law_id.iloc[0]
print(edges[edges.tgt_law_id==target].src_law.tolist())
```
Load into NetworkX / Neo4j for centrality, community detection, or as a **RAG substrate**
(retrieve a statute → expand to its cited/citing articles).

### Use it from an LLM — MCP server (`mcp/`)
Expose the graph + deterministic resolver to Claude/LLMs over the Model Context Protocol:
`resolve_citation`, `what_cites`, `what_law_cites`, `citation_path`, `get_law`. See [`mcp/README.md`](mcp/README.md).

### Evaluation harness (`eval/`)
Precision/recall labeling samples + `compute_kappa.py` / `aggregate_precision.py`, and
[`eval/EVAL_PROTOCOL.md`](eval/EVAL_PROTOCOL.md) — how the *preliminary* figures (see [docs/METHODOLOGY.md](docs/METHODOLOGY.md))
are upgraded to validated measurements via blind multi-annotator labeling.

## Reproduce from scratch
Pure Python standard library — no third-party dependencies (Python 3.10+).
```bash
cd src
python fetch_egov.py --out snapshot/                 # download an e-Gov law snapshot
python build_graph.py --corpus snapshot/ --out ../data/   # parse → extract → resolve → export
```
Deterministic: same snapshot + same code → byte-identical graph. (Reproducing from an existing
snapshot directory only needs `build_graph.py`; `fetch_egov.py` just refreshes the corpus.)

### Code (`src/jlawcite/`) — the deterministic resolver, reusable on its own
```python
from jlawcite import citation, resolver, parser
refs, _ = citation.extract_external("会社法第七百三十七条第二項の…")   # -> ExtRef(law='会社法', art=737, …)
```
`parser` (e-Gov XML → 条/項/号), `citation` (rule-based extraction + in-law definition anaphora),
`resolver` (`LawNameIndex`: promulgation/canonical/旧法令名/alias/over-grab-trim resolution).

## Honest limitations
- **Recall is not complete (~68% raw).** Misses are dominated by (a) extraction artifacts / co-references and
  (b) **out-of-scope targets** — repealed/renamed laws, treaties, foreign law that have *no node* in a
  current-only corpus. Verified edges are correct; the graph is a high-precision **lower bound**, not exhaustive.
- **Current-version only.** ~22% of edges are version-bound references (`旧法`/`改正前`) that collapse to the
  current version. Not suitable for amendment-propagation analysis without a version layer.
- **National statutes only** — no local ordinances (条例) or case law.
- Precision is validated by sample labeling (LLM-proposed + human spot-check); a larger blind multi-annotator
  round is future work.

## Contributing
Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The limitations above *are* the roadmap; good places to help:
- **Blind annotation round** → makes precision/recall *validated* instead of preliminary (label `eval/precision_sample.csv` / `eval/recall_gold_sample.csv`; see [eval/EVAL_PROTOCOL.md](eval/EVAL_PROTOCOL.md)).
- **Version-aware layer** → resolve the ~22% version-bound edges to specific versions (enables amendment-propagation).
- **Coverage** → local ordinances (条例) / case law; standard-abbreviation dictionary expansion.
- **Spotted a wrong edge or a missing citation?** Open a *data issue* (templates in `.github/`).

## License
Code: Apache-2.0. Data/graph: CC-BY-4.0 (source: e-Gov 法令データ, public). See `LICENSE`, `DATA_CARD.md`.

## Citation
```
@misc{jlaw_citegraph_2026,
  title  = {JLaw-CiteGraph: An open citation graph of Japanese statutory law},
  year   = {2026},
  note   = {e-Gov 2026-06-23 snapshot},
  url    = {https://github.com/yabooung/jp-law-citation-graph}
}
```
