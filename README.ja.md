# JLaw-CiteGraph 🇯🇵⚖️

[English](README.md) · **日本語** · [한국어](README.ko.md)

![code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue) ![data: CC BY 4.0](https://img.shields.io/badge/data-CC--BY--4.0-green) ![deterministic](https://img.shields.io/badge/pipeline-deterministic%20·%20no%20LLM-brightgreen) ![version](https://img.shields.io/badge/release-v2.1.0-informative) [![PyPI](https://img.shields.io/pypi/v/jlawcite)](https://pypi.org/project/jlawcite/) [![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97-dataset-yellow)](https://huggingface.co/datasets/dbwjspdlagjdyd/jp-law-citation-graph)

**日本の法令の引用関係を決定論的に解決した、オープンな引用グラフと検索インデックス。**

公式 [e-Gov](https://laws.e-gov.go.jp/) の法令XMLから、現行の全法令を条・項・号まで解析し、本文中の
引用を参照先の規定に解決しています（同一法令内 92.9%、他法令 82.2%。解決できなかった引用も一覧で公開）。データファイル、単一ファイルのエクスプローラ、埋め込み不要の
検索CLI `jlawcite`、LLM向けのMCPサーバーを同梱しています。

[![JLaw-CiteGraph インタラクティブ・エクスプローラ](assets/explorer-screenshot.png)](explorer.html)

<sub>[`explorer.html`](explorer.html) — 法令を選ぶと、その引用先（緑）と被引用元（黄）が表示されます。</sub>

## 概要（v2.0、e-Gov 2026-09-27 スナップショット）

| | |
|---|---|
| **法令** | 8,998（2026-09-29 時点で施行中の版）＋ **施行予定の改正 1,649件**（施行日・改正法令） |
| **グラフ** | 189万ノード（条・項・号・附則・別表）· 引用エッジ 142万 · 委任（政令で定める）67,666 · 別表/様式参照 37,377 |
| **法令間ネットワーク** | 法令ペア 70,577 · 条レベルの法令間リンク 453,390 |
| **引用解決率** | 同一法令内 92.9% · 他法令 82.2% · 前条/同項などの指示語 92.2% |
| **精度** | エッジの86%を占める規則の手作業サンプルで約98%（暫定 — 下記参照） |
| **検索** | `jlawcite get 民法第七百九条` · BM25検索 · 実際の税務質問1,170件で引用グラフを使うと Recall@10 が 0.24 → 0.46 |
| **手法** | 100%決定論的（規則＋辞書＋文書内文脈）。LLMなし。e-Gov一括ダウンロードから再現可能 |
| **更新** | e-Govから毎月再構築。各スナップショットはHugging Faceにタグ付け（`jlawcite download --list`、`--snapshot YYYY-MM-DD` で固定） |

## v2 の変更点

| | v1.0（2026-06） | **v2.0（2026-09）** |
|---|---|---|
| 単位 | 法令→法令（条は文字列） | 条・項・号ノード（附則・別表を含む） |
| エッジ | 法令間引用 | ＋同一法令内引用、前条/同項/前号、委任、別表参照 |
| 条レベルの法令間リンク（重複除去） | 173,844 | **453,390** |
| 法令ペア | 55,651 | **70,577** |
| 版 | 法令ごとの最新ファイル | 基準日に施行中の版＋施行予定の改正 |
| 検索 | – | `jlawcite` CLI（条文参照・BM25・グラフ探索）＋検索ベンチマーク |
| 精度 | 誤り0 / 400（LLM提案ラベル） | 規則別サンプルと信頼区間。誤りの型を5つ発見・修正 |

v1 は同じ引用の*出現ごと*に1行を書いていたため、121万行のうち異なるリンクは173,844でした。
v2 は（出典, 参照先）の組を1回だけ数えます。詳細は [CHANGELOG.md](CHANGELOG.md)。

## クイックスタート
```bash
pip install jlawcite                                 # PyPI から CLI とライブラリ
jlawcite download                                    # 構築済み検索DB（約680MB、最新の月次スナップショット）
jlawcite get 民法第七百九条

# グラフを再構築する場合:
git clone https://github.com/yabooung/jp-law-citation-graph && cd jp-law-citation-graph
pip install -e .                                     # Python 3.11+

jlawcite fetch                                       # e-Gov 一括XML（約320MB）
jlawcite build --input data/raw/law_xml \
    --csv data/raw/law_xml/all_law_list.csv --output data/parsed      # 約5分・決定論的
jlawcite validate --data data/parsed                 # 整合性チェック11項目
jlawcite index                                       # 検索インデックス（約1.5分、2.6GB）

jlawcite get 民法第七百九条                           # 労働基準法20条1項、激甚法第三条なども可
jlawcite search 解雇 予告                             # BM25。質問文は --nl
jlawcite refs 労働基準法第二十条                       # 引用先・被引用元
jlawcite pending --until 20261231                    # 施行予定の改正
```

## データ（`/data`）
| ファイル | 内容 |
|---|---|
| `laws.csv` | v1 の列＋ `enforcement_date, next_enforcement_date, pending_versions` |
| `cites_law_to_law.csv` | 法令→法令の集計（v1 の列） |
| `cites_edges.jsonl.gz` | 法令名で示された引用すべて。v1 の項目＋ `src_node`, `tgt_node`, `fallback_level` |
| `cites_all_edges.jsonl.gz` | グラフの全エッジ（同一法令内・前条/同項・委任・別表参照・改正） |
| `pending_versions.csv` | 施行予定の改正（施行日・施行日備考・改正法令・e-Gov URL） |

全ノード（189万、本文付き）は GitHub Release に添付するか、クイックスタートで再生成できます。

## MCPサーバー（`mcp/`）
v1 の5ツールに加え、v2 では `get_provision`（引用文字列→条文）、`search_statutes`、
`pending_amendments` を追加しました。[`mcp/README.md`](mcp/README.md)

## 検索ベンチマーク
国税庁「質疑応答事例」1,170件（回答が根拠条文を示すもの）について、質問文をクエリとし、条単位で評価します。

| method | R@1 | R@5 | R@10 | R@20 | R@50 | MRR@50 | s/query |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 (character-trigram OR) | 0.086 | 0.192 | 0.244 | 0.326 | 0.437 | 0.140 | 0.11 |
| BM25 + 1-hop citation graph | **0.256** | **0.403** | **0.459** | **0.500** | **0.550** | **0.325** | 0.11 |

<sub>1,170 queries · e-Gov snapshot 2026-09-27 · `eval/v2/nta_retrieval_results.json`</sub>

1ホップ展開では、上位の検索結果が引用する条文にスコアを分配します。施行令の項がヒットすると、
それが引用する本法の条も上がってきます。いずれも埋め込みを使わない基準値です。

## 品質と制約
- 本文のない法令は0件、整合性チェック11項目はすべて通過し、同じ入力からは同じ出力になります。
- 解決率の分母からは、コーパス外を参照する引用（改正前の法令、改正法、改正法附則内の引用）を除いています。件数は `jp_cites_stats.json` に別途記録しています。
- **精度は暫定値です。** 開発中に無作為抽出したエッジ180件（規則ごとに10〜20件）を原文と照合し、見つかった誤りの型5つを修正しました。サンプルが小さく、ブラインド評価でもないため目安としてください。改正法附則内の引用は約40%しか正しくないため、confidence 0.4 を付けています。詳細は [docs/METHODOLOGY.md](docs/METHODOLOGY.md)。
- 対象は現行の国の法令のみです。判例・通達・条例・廃止法令や改正法の本文は含みません。イ・ロ・ハの細目は号に含めています。

## 関連研究
弁護士ドットコムの引用グラフ（DDS 2026、非公開）、[DaisukeHori/japan-law](https://github.com/DaisukeHori/japan-law)（CC0、評価なし）、法令の参照解決（Tran ら, ICAIL 2013）、参照構造を用いた条文検索（Mizuno・狩野, COLIEE 2025 ほか）があります。本プロジェクトは同一法令内の引用と指示語、版の扱い、規則別の精度、全法令での検索評価を公開データとして加えます。詳細は [README.md](README.md#related-work)。

## ライセンス・引用
コード: Apache-2.0。データ: CC BY 4.0（出典：e-Gov法令データ。`eval/v2/nta_gold.jsonl` は国税庁ホームページを加工）。
法的判断には e-Gov・官報の原文を確認してください。引用は [README.md](README.md#citation) の BibTeX をお使いください。
