# JLaw-CiteGraph 🇯🇵⚖️

[English](README.md) · [日本語](README.ja.md) · **한국어**

![code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue) ![data: CC BY 4.0](https://img.shields.io/badge/data-CC--BY--4.0-green) ![deterministic](https://img.shields.io/badge/pipeline-deterministic%20·%20no%20LLM-brightgreen)

**일본 법령 간 인용 관계를 결정론적으로 해소한, 최초의 오픈 인용 그래프.**

공식 [e-Gov](https://laws.e-gov.go.jp/) 법령 XML에서 결정론적으로 추출하고, 모든 엣지를 특정
법령·조에 해소한 재현 가능한 인용 그래프입니다. 정밀도는 층화 표본으로 검증했습니다(잠정 — "한계" 참조).

[![JLaw-CiteGraph 인터랙티브 익스플로러](assets/explorer-screenshot.png)](explorer.html)

<sub>단일 파일 **[`explorer.html`](explorer.html)** — 법령을 고르면 그 법령이 인용하는 것(초록)과
인용하는 법령(노랑)이 보입니다. 표시: 地方自治法(지방자치법), 피인용 최다(1,220개 법령).</sub>

> **포함:** 그래프(CSV/JSONL) · 단일 파일 인터랙티브 **explorer**(`explorer.html`) ·
> 재사용 가능한 결정론적 Python 리졸버(`jlawcite`) · 그리고 LLM(Claude 등)이 그래프를 직접
> 질의할 수 있는 **🔌 MCP 서버** — [`mcp/`](mcp/README.md).

| | |
|---|---|
| **법령(노드)** | 8,980개 법령(e-Gov XML 10,229파일, 2026-06-23 스냅샷) |
| **해소된 외부 엣지** | **1,212,708**(조 단위) — 그중 **722,426이 법령 간**(법령 A→법령 B) + 490,282가 자기/버전 참조(부칙 내 新法/旧法) · **55,651개 고유 법령-법령 쌍** |
| **법령 내(intra-law) 엣지** | 약 3.6M 추출(본 릴리스는 **법령 간** 그래프를 제공) |
| **엣지 정밀도** | *잠정치.* 경로 층화 표본 400건에서 확인(현재까지 확인된 오류 없음) — 단 **blind 검증 전**이라, 검증된 정밀도가 아니라 *지표*로 봐주세요. ([검증 기여 →](#기여) · [방법](docs/METHODOLOGY.md)) |
| **외부 해소율(recall)** | **원시 68%** · 범위 내 실질 인용에서 약 85–90%*(소표본 추정)* |
| **방법** | 100% 결정론(정규식+사전+규칙 기반 해소) — *LLM 없음·무작위성 없음·완전 재현 가능·감사 가능* |

> ⚠️ **먼저 읽어주세요:** 이 그래프는 고정밀 **하한(lower bound)**이지 *완전한* 인용 목록이 아닙니다. 원시 recall은 약 68% — **엣지가 없다고 "인용이 없다"는 뜻이 아닙니다.** 망라적·권위적 출처로 사용하지 마세요([정직한 한계](#정직한-한계) 참조).

> 왜 중요한가: e-Gov는 법령의 *본문*은 주지만, 해소된 *인용 네트워크*는 주지 않습니다. 그걸 만들려면
> 약칭(`金商法`→`金融商品取引法`), 법령 내 조응(`旧法`/`新法`/`同法`), over-grab, 개명 법령(`旧法令名`)을
> 해소해야 합니다. 이 repo는 그것을 결정론적으로 수행하고 그래프를 제공합니다.

---

> **릴리스 = 날짜 스냅샷.** `v1`은 **e-Gov 2026-06-23** 스냅샷 — 고정·인용 가능·재현 가능한 시점
> (연구에 적합한 형태). *현행* 그래프가 필요하면 `src/fetch_egov.py`로 재생성하면 되며, 이 repo의
> 갱신에 의존하지 않습니다.

## 누구를 위한 것인가
| 당신이… | 활용 |
|---|---|
| **법률 NLP 연구자** | 조문 검색/RAG를 인용 이웃으로 확장, 또는 `jlawcite`로 자기 코퍼스의 인용을 해소(예: COLIEE 조문 과제) |
| **법률테크 개발자** | "X를 참조하는 법령은?"에 답 — 예: 개인정보보호법 개정 시 **110**개 의존 법령 색출(검증된 하한) |
| **비교법/네트워크 연구자** | 법 구조 연구: 허브(地方自治法은 1,220개 법령에서 피인용), 중심성, 의존 클러스터(NetworkX/Neo4j로) |
| **LLM 법률 어시스턴트 개발** | 인용을 결정론적으로 접지 — `会社法第737条`→특정 법령·조 해소, 환각 없음 |
| **호기심** | `explorer.html`을 열고 일본 법령의 연결을 클릭하며 탐색 |

## 내용(`/data`)
- **`laws.csv`** — 노드: `law_id, name, type, url`
- **`cites_law_to_law.csv`** — 집계 엣지: `src_law_id, src_law, tgt_law_id, tgt_law, n_citations`(네트워크 분석에 유용)
- **`cites_edges.jsonl.gz`** — 전체 엣지: `src_law/src_article → tgt_law/tgt_article`, `via`(해소 경로) + `confidence` 포함

모든 엣지는 `via` ∈ {`canonical`, `promulgation`, `alias`, `old_name`, `prefix_stripped`, `suffix`,
`local_def`, `local_def_tail`}와 `confidence`를 지녀, 고신뢰 부분집합으로 필터링할 수 있습니다.

## 한눈에(그래프에서 계산)
**피인용이 많은 법령(허브)** — *다른* 법령 몇 개가 인용하는가:
| 법령 | 피인용 |
|---|---|
| 地方自治法 (지방자치법) | 1,220 |
| 会社法 (회사법) | 629 |
| 児童福祉法 (아동복지법) | 500 |
| 行政手続法 (행정절차법) | 462 |
| 民法 (민법) | 411 |

**영향 분석** — "X를 인용하는 것은?" → 검증된 하한: `個人情報保護法`(개인정보보호법) ← **110개 법령**.

## 사용
```python
import pandas as pd
laws  = pd.read_csv("data/laws.csv")
edges = pd.read_csv("data/cites_law_to_law.csv")

# 피인용 많은 허브 법령
hubs = edges.groupby(["tgt_law_id","tgt_law"])["src_law_id"].nunique() \
            .sort_values(ascending=False).head(20)

# 영향 집합: 특정 법령을 인용하는 법령은?
target = laws[laws.name=="個人情報の保護に関する法律"].law_id.iloc[0]
print(edges[edges.tgt_law_id==target].src_law.tolist())
```
NetworkX / Neo4j로 불러와 중심성·커뮤니티 탐지, 또는 **RAG 기반**으로
(조문을 검색→인용/피인용 조로 확장).

### LLM에서 사용 — MCP 서버(`mcp/`)
그래프 + 결정론적 리졸버를 Model Context Protocol로 Claude/LLM에 노출:
`resolve_citation`, `what_cites`, `what_law_cites`, `citation_path`, `get_law`. [`mcp/README.md`](mcp/README.md) 참조.

### 평가 하네스(`eval/`)
정밀도/recall 라벨링 표본 + `compute_kappa.py` / `aggregate_precision.py`, 그리고
[`eval/EVAL_PROTOCOL.md`](eval/EVAL_PROTOCOL.md) — *잠정* 수치([docs/METHODOLOGY.md](docs/METHODOLOGY.md) 참조)를
blind 다중 어노테이터로 검증된 측정값으로 끌어올리는 절차.

## 처음부터 재현
순수 Python 표준 라이브러리 — 서드파티 의존성 없음(Python 3.10+).
```bash
cd src
python fetch_egov.py --out snapshot/                 # e-Gov 법령 스냅샷 다운로드
python build_graph.py --corpus snapshot/ --out ../data/   # parse → extract → resolve → export
```
결정론적: 같은 스냅샷 + 같은 코드 → 바이트 단위로 동일한 그래프. (기존 스냅샷 디렉토리에서
재현하려면 `build_graph.py`만 있으면 됨. `fetch_egov.py`는 코퍼스 갱신용.)

### 코드(`src/jlawcite/`) — 단독으로도 재사용 가능한 결정론적 리졸버
```python
from jlawcite import citation, resolver, parser
refs, _ = citation.extract_external("会社法第七百三十七条第二項の…")   # -> ExtRef(law='会社法', art=737, …)
```
`parser`(e-Gov XML → 条/項/号), `citation`(규칙 기반 추출 + 법령 내 정의 조응),
`resolver`(`LawNameIndex`: 법령번호/정식명/旧法令名/약칭/over-grab 트림 해소).

## 정직한 한계
- **recall은 완전하지 않음(원시 약 68%).** 누락의 대부분은 (a) 추출 아티팩트/공참조, (b) **범위 밖
  타깃** — 폐지/개명 법령, 조약, 외국법(현행만 담은 코퍼스에 *노드가 없음*). 검증된 엣지는 정확하며,
  그래프는 고정밀 **하한(lower bound)**이지 망라적이지 않습니다.
- **현행 버전만.** 엣지의 약 22%는 버전 종속 참조(`旧法`/`改正前`)로 현행 버전으로 붕괴됩니다. 버전
  레이어 없이는 개정 전파 분석에 부적합합니다.
- **국가 법령만** — 조례(条例)나 판례는 없습니다.
- 정밀도는 표본 라벨링(LLM 제안 + 사람 스폿체크)으로 검증. 더 큰 blind 다중 어노테이터 라운드는 향후 과제.

## 기여
Issue·PR 환영 — [CONTRIBUTING.md](CONTRIBUTING.md) 참조. 위 한계가 곧 로드맵입니다. 도움이 필요한 곳:
- **blind 어노테이션 라운드** → 정밀도/recall을 *잠정*에서 *검증된* 값으로(`eval/precision_sample.csv` / `eval/recall_gold_sample.csv` 라벨링; [eval/EVAL_PROTOCOL.md](eval/EVAL_PROTOCOL.md)).
- **버전 레이어** → 약 22%의 버전 종속 엣지를 특정 버전으로 해소(개정 전파 분석 가능).
- **커버리지** → 조례(条例)/판례, 표준 약칭 사전 확장.
- **틀린 엣지나 누락된 인용을 발견했다면?** *데이터 이슈*를 열어주세요(템플릿은 `.github/`).

## 라이선스
코드: Apache-2.0. 데이터/그래프: CC-BY-4.0(출처: e-Gov 法令データ, 공개). `LICENSE`, `DATA_CARD.md` 참조.

## 인용
```
@misc{jlaw_citegraph_2026,
  title  = {JLaw-CiteGraph: An open citation graph of Japanese statutory law},
  year   = {2026},
  note   = {e-Gov 2026-06-23 snapshot},
  url    = {https://github.com/yabooung/jp-law-citation-graph}
}
```
