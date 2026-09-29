# JLaw-CiteGraph 🇯🇵⚖️

[English](README.md) · [日本語](README.ja.md) · **한국어**

![code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue) ![data: CC BY 4.0](https://img.shields.io/badge/data-CC--BY--4.0-green) ![deterministic](https://img.shields.io/badge/pipeline-deterministic%20·%20no%20LLM-brightgreen) ![version](https://img.shields.io/badge/release-v2.2.0-informative) [![PyPI](https://img.shields.io/pypi/v/jlawcite)](https://pypi.org/project/jlawcite/) [![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97-dataset-yellow)](https://huggingface.co/datasets/dbwjspdlagjdyd/jp-law-citation-graph)

**일본 법령의 인용 관계를 결정론적으로 해석한 공개 인용 그래프이자 검색 인덱스입니다.**

일본 정부 공식 [e-Gov](https://laws.e-gov.go.jp/) 법령 XML에서 현행 법령 전체를 조·항·호 단위까지 파싱하고,
본문 속 인용을 실제로 가리키는 조문에 연결했습니다(같은 법령 안 92.9%, 다른 법령 82.2%. 연결하지 못한 인용도 목록으로 공개). 데이터 파일, 단일 파일 탐색기, 임베딩 없이 동작하는
검색 CLI `jlawcite`, LLM용 MCP 서버를 함께 제공합니다.

[![JLaw-CiteGraph 탐색기](assets/explorer-screenshot.png)](explorer.html)

<sub>[`explorer.html`](explorer.html): 법령을 고르면 그 법령이 인용하는 법령(녹색)과 그 법령을 인용하는 법령(노랑)이 보입니다.</sub>

## 한눈에 보기 (v2.0, e-Gov 2026-09-27 스냅샷)

| | |
|---|---|
| **법령** | 8,998개 (2026-09-29 기준 시행 중인 버전) + **시행 예정 개정 1,649건** (시행일·개정법령) |
| **그래프** | 노드 189만 (조·항·호·附則·별표) · 인용 엣지 142만 · 위임(政令で定める) 67,666 · 별표/様式 참조 37,377 |
| **법령 간 네트워크** | 법령 쌍 70,577 · 조 단위 법령 간 링크 453,390 |
| **인용 해석률** | 같은 법령 안 92.9% · 다른 법령 82.2% · 前条·同項 같은 지시어 92.2% |
| **정확도** | 전체 엣지의 86%를 차지하는 규칙들을 수작업 표본으로 점검한 결과 약 98% (예비 수치, 아래 참고) |
| **검색** | `jlawcite get 民法第七百九条` · BM25 검색 · 실제 세무 질문 1,170건에서 인용 그래프를 쓰면 Recall@10이 0.24 → 0.46 |
| **방법** | 100% 결정론적 (규칙 + 사전 + 문서 내 문맥). LLM 없음. e-Gov 일괄 다운로드에서 그대로 재현 |
| **갱신** | 매월 e-Gov에서 다시 빌드. 스냅샷마다 Hugging Face에 태그 (`jlawcite download --list`, `--snapshot YYYY-MM-DD`로 고정) |

## v2에서 달라진 점

| | v1.0 (2026-06) | **v2.0 (2026-09)** |
|---|---|---|
| 단위 | 법령 → 법령 (조는 문자열로만) | 조·항·호 노드 (附則·별표 포함) |
| 엣지 | 법령 간 인용 | + 같은 법령 안 인용, 前条/同項/前号, 위임, 별표 참조 |
| 조 단위 법령 간 링크 (중복 제거) | 173,844 | **453,390** |
| 법령 쌍 | 55,651 | **70,577** |
| 버전 | 법령별 최신 파일 | 기준일에 시행 중인 버전 + 시행 예정 개정 |
| 검색 | 없음 | `jlawcite` CLI (조문 조회·BM25·그래프 탐색) + 검색 벤치마크 |
| 정확도 | 오류 0 / 400 (LLM이 제안한 라벨) | 규칙별 표본과 신뢰구간. 오류 유형 5가지를 찾아 수정 |

v1은 같은 인용이 *나올 때마다* 한 줄씩 기록해서, 121만 줄 중 서로 다른 링크는 173,844개였습니다.
v2는 (출처, 대상) 쌍을 한 번만 셉니다. 자세한 내용은 [CHANGELOG.md](CHANGELOG.md)에 있습니다.

## 빠른 시작
```bash
pip install jlawcite                                 # PyPI에서 CLI·라이브러리 설치
jlawcite download                                    # 미리 빌드한 검색 DB (다운로드 약 115MB, 풀기 약 1분)
jlawcite get 民法第七百九条

# 그래프를 직접 다시 빌드하려면:
git clone https://github.com/yabooung/jp-law-citation-graph && cd jp-law-citation-graph
pip install -e .                                     # Python 3.11+

jlawcite fetch                                       # e-Gov 일괄 XML (약 320MB)
jlawcite build --input data/raw/law_xml \
    --csv data/raw/law_xml/all_law_list.csv --output data/parsed      # 약 5분, 결정론적
jlawcite validate --data data/parsed                 # 무결성 검사 11개
jlawcite index                                       # 검색 인덱스 (약 1.5분, 2.6GB)

jlawcite get 民法第七百九条                           # 労働基準法20条1項, 激甚法第三条 형식도 가능
jlawcite search 解雇 予告                             # BM25, 질문 문장은 --nl
jlawcite refs 労働基準法第二十条                       # 인용하는 조문 / 인용되는 조문
jlawcite pending --until 20261231                    # 시행 예정 개정
```

## 데이터 (`/data`)
| 파일 | 내용 |
|---|---|
| `laws.csv` | v1 열 + `enforcement_date, next_enforcement_date, pending_versions` |
| `cites_law_to_law.csv` | 법령 → 법령 집계 (v1 열 그대로) |
| `cites_edges.jsonl.gz` | 법령 이름으로 가리킨 인용 전체. v1 필드 + `src_node`, `tgt_node`, `fallback_level` |
| `cites_all_edges.jsonl.gz` | 그래프의 모든 엣지 (같은 법령 안·前条/同項·위임·별표 참조·개정) |
| `pending_versions.csv` | 시행 예정 개정 (시행일·施行日備考·개정법령·e-Gov URL) |

전체 노드 파일(189만 개, 본문 포함)은 GitHub Release에 첨부되어 있고, 빠른 시작 명령으로 다시 만들 수도 있습니다.

## MCP 서버
Claude Code에서는 한 줄로 추가합니다([uv](https://docs.astral.sh/uv/) 필요, 데이터는 처음 실행할 때 자동으로 받음):
```bash
claude mcp add jlawcite -- uvx --from "jlawcite[mcp]" jlawcite mcp
```
v1의 도구 5개에 더해 v2에서 `get_provision`(인용 문자열 → 조문 본문), `search_statutes`,
`pending_amendments`가 추가됐습니다. 자세한 사용법은 [`mcp/README.md`](mcp/README.md)에 있습니다.

## 검색 벤치마크
국세청 「質疑応答事例」 1,170건을 씁니다. 모두 답변이 근거 조문을 밝힌 사례입니다. 질문문을 질의로 쓰고, 조 단위로 채점합니다.

| method | R@1 | R@5 | R@10 | R@20 | R@50 | MRR@50 | s/query |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 (character-trigram OR) | 0.086 | 0.192 | 0.244 | 0.326 | 0.437 | 0.140 | 0.11 |
| BM25 + 1-hop citation graph | **0.256** | **0.403** | **0.459** | **0.500** | **0.550** | **0.325** | 0.11 |

<sub>1,170 queries · e-Gov snapshot 2026-09-27 · `eval/v2/nta_retrieval_results.json`</sub>

1단계 확장은 상위 검색 결과가 인용하는 조문에 점수를 나눠 줍니다. 施行令 항이 검색되면 그 항이 인용한
모법 조문도 함께 올라옵니다. 두 방법 모두 임베딩을 쓰지 않는 기준선입니다.

## 품질과 한계
- 본문 없는 법령은 0개입니다. 무결성 검사 11개를 모두 통과했고, 같은 입력이면 같은 출력이 나옵니다.
- 해석률의 분모에서는 대상 본문이 코퍼스에 없는 인용(개정 전 법령, 개정법, 개정법 附則 안의 인용)을 뺐습니다. 이 인용들은 `jp_cites_stats.json`에 따로 집계합니다.
- **정확도는 예비 수치입니다.** 개발 과정에서 무작위로 뽑은 엣지 180건(규칙당 10–20건)을 원문과 대조했고, 여기서 찾은 오류 유형 5가지를 고쳤습니다. 표본이 작고 블라인드 평가도 아니므로 참고용으로만 봐 주세요. 개정법 附則 안의 인용은 약 40%만 맞아서 confidence 0.4로 표시했습니다. 자세한 내용은 [docs/METHODOLOGY.md](docs/METHODOLOGY.md)와 [docs/ko/DATASET.md](docs/ko/DATASET.md)에 있습니다.
- 범위는 현행 국가 법령뿐입니다. 판례·통달·조례, 폐지 법령과 개정법의 본문은 들어 있지 않습니다. イ·ロ·ハ 세목은 호 본문에 합쳐져 있습니다.

## 관련 연구
弁護士ドットコム의 인용 그래프(DDS 2026, 비공개), [DaisukeHori/japan-law](https://github.com/DaisukeHori/japan-law)(CC0, 평가 없음), 법령 참조 해석(Tran 외, ICAIL 2013), 참조 구조를 쓴 조문 검색(Mizuno·狩野, COLIEE 2025 등)이 있습니다. 이 프로젝트는 여기에 같은 법령 안 인용과 지시어, 버전 처리, 규칙별 정확도, 전 법령 대상 검색 평가를 공개 데이터로 더합니다. 자세한 내용은 [README.md](README.md#related-work)에 있습니다.

## 상세 문서 (한국어)
[데이터셋 카드](docs/ko/DATASET.md) · [스키마·해석 규칙](docs/ko/GRAPH_SCHEMA.md) · [검색 도구](docs/ko/SEARCH.md) · [개선 핸드북](docs/ko/IMPROVING_THE_GRAPH.md)

## 라이선스·인용
코드는 Apache-2.0, 데이터는 CC BY 4.0입니다. 출처는 e-Gov 법령 데이터이고, `eval/v2/nta_gold.jsonl`은 국세청 홈페이지 자료를 가공한 것입니다.
법률 자문이 아닙니다. 법적 판단에는 e-Gov·官報 원문을 확인하세요. 인용 형식은 [README.md](README.md#citation)의 BibTeX를 쓰면 됩니다.
