---
license: cc-by-4.0
language:
- ja
pretty_name: JLaw-CiteGraph
tags:
- legal
- japanese-law
- citation-graph
- statute
- legal-information-retrieval
task_categories:
- text-retrieval
size_categories:
- 1M<n<10M
configs:
- config_name: laws
  data_files:
  - split: train
    path: data/laws.csv
- config_name: cites_edges
  default: true
  data_files:
  - split: train
    path: data/cites_edges.jsonl.gz
- config_name: cites_all_edges
  data_files:
  - split: train
    path: data/cites_all_edges.jsonl.gz
- config_name: cites_law_to_law
  data_files:
  - split: train
    path: data/cites_law_to_law.csv
- config_name: pending_versions
  data_files:
  - split: train
    path: data/pending_versions.csv
- config_name: nta_retrieval
  data_files:
  - split: test
    path: eval/nta_gold.jsonl
---

> Code, CLI (`pip install jlawcite`), MCP server and interactive explorer:
> **https://github.com/yabooung/jp-law-citation-graph**
>
> `nta_retrieval`: <!--v:gold_records-->1,598<!--/v--> NTA 質疑応答事例 cases (collected 2026-09-29), of which the <!--v:queries-->1,186<!--/v--> with a non-empty `gold_articles` are the retrieval benchmark queries (source: 国税庁ホームページ, edited; attribution required).
