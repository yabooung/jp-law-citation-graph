# jlawcite — 임베딩 없는 법령 검색 도구

`data/parsed/`(ingest 산출물)를 SQLite 파일 하나로 색인해서, 서버·GPU·임베딩 없이
세 가지 방식으로 일본 법령을 찾는다.

| 방식 | 명령 | 쓰임 |
|---|---|---|
| 조문 직접 조회 | `get 民法第七百九条` | 인용 문자열·약칭·공포번호로 정확한 조문 본문 |
| 키워드 검색 | `search 解雇 予告` | BM25 전문검색 (trigram) |
| 자연어 질의 | `search --nl "…場合の居住者の判定"` | 문장형 질의, 문자 trigram OR + BM25 |
| 그래프 탐색 | `refs 労働基準法第二十条` | 인용하는/인용되는 조문, 위임, 별표 |
| 법령 정보 | `law 民法 --toc`, `pending` | 현행 시행일, 개정 예정, 목차 |

모든 명령은 `--json`으로 JSON Lines를 출력한다 (연구 파이프라인 연결용).

---

## 1. 설치와 색인

```bash
pip install -e .
jlawcite fetch  --output data/raw/law_xml          # e-Gov 원천 (약 320MB)
jlawcite build --input data/raw/law_xml \
    --csv data/raw/law_xml/all_law_list.csv --output data/parsed  # 약 5분
jlawcite index                                           # 약 1.5분 → data/search/jp_search.sqlite
```

`build` 옵션: `--data`(ingest 출력, 기본 `data/parsed`), `--csv`(旧法令名 조회용, 선택),
`--aliases`(약칭 사전), 전역 `--db`(출력 경로). 기존 DB는 덮어쓴다(임시 파일에 만든 뒤 교체).

색인 결과 (2026-09-27 스냅샷): 노드 1,886,996 · 법령 8,998 · 검색 청크 852,170 ·
엣지 1,522,808 · 파일 약 2.6GB.

---

## 2. 명령

### `get` — 인용 문자열 → 본문

```text
$ jlawcite get 労働基準法20条1項
労働基準法  [322AC0000000049, act, 昭和二十二年法律第四十九号]  現行 2026-07-17 施行中, 次回改正 2027-04-01
[322AC0000000049_a20_p1] Paragraph

使用者は、労働者を解雇しようとする場合においては、少くとも三十日前にその予告をしなければならない。…

改正予定:
  2027-04-01  労働基準法 ← 労働者災害補償保険法等の一部を改正する法律 令和八年法律第六十号
```

받는 형식:

| 입력 | 예 |
|---|---|
| 정식 법령명 + 위치 | `民法第七百九条`, `会社法第二条第一項第十二号の二` |
| 아라비아 숫자, 「第」 생략 | `所得税法施行令14条2項`, `民法 709条` |
| 附則 | `所得税法附則第2条` (제정 附則) |
| 공식 약칭 (LawTitle@Abbrev) | `激甚法第三条`, `番号法第2条`, `独禁法` |
| 공포번호 | `昭和二十二年法律第四十九号第二十条` |
| 旧法令名 | CSV의 `旧法令名` 열 (build 시 `--csv`) |
| 노드 ID | `322AC0000000049_a20_p1` |
| 법령명만 | `民法` → Law 노드 |
| 조문만 | `第七百九条 --law 民法` |

조(Article)를 조회하면 항·호를 모두 조립한 본문을 돌려준다. 항이 없으면 가까운 상위
노드로 내려가고 `note`에 알린다. 법령명이 모호하면 후보 목록과 함께 종료 코드 2.

### `search` — 키워드 검색

```bash
jlawcite search 解雇 予告                 # 공백 = AND
jlawcite search 税額控除 --law 租税特別措置法 --section main
jlawcite search 個人情報 --type act --limit 50 --offset 50
jlawcite search --nl "海外勤務から1年未満で帰国した場合の居住者の判定"
```

- **검색 단위(청크)** = 항(Paragraph / 附則 항) 하나 + 그 아래 호 전부, 또는 별표·様式 하나.
  조 제목만 있는 Article은 본문이 없으므로 청크가 아니다.
- **3자 이상 검색어**는 FTS5 trigram 색인과 BM25(제목 가중치 2, 본문 1)로 찾는다.
  **1–2자**(解雇, 税額 등 일본어에 흔함)는 부분문자열 필터로 처리하고, 검색어가 모두 짧으면
  길이 대비 출현 빈도로 정렬한다.
- `--nl`: 문장을 받아 한자·가타카나·숫자 구간의 문자 trigram을 OR로 묶는다. 조사·활용어미(히라가나)는
  구분자로 본다. 분할 없는 일본어에서 흔히 쓰는 n-gram 기준선이다.
- 필터: `--law`(이름·ID·공포번호), `--type act|cabinet_order|ministerial|imperial_order|dajokan|other`,
  `--section main|suppl`, `--include-inactive`(미시행 법령 포함). 기본은 시행 중인 법령만.
- `--full`: 청크 전문 출력.

### `refs` — 인용 그래프

```bash
jlawcite refs 労働基準法第二十条                       # 양방향
jlawcite refs 民法第七百九条 --direction in --limit 500
jlawcite refs 322AC0000000049_a20 --rel CITES --rel REFERS_TO_ATTACHMENT
```

조(Article)를 주면 그 아래 항·호에서 나가고 들어오는 엣지를 모두 합친다. 법령 ID를 주면 법령 전체다.
각 엣지에 `raw`(원문 인용 표현)와 `extracted_from`(해소 방식, [GRAPH_SCHEMA_V2 §4.5](GRAPH_SCHEMA.md))이
붙어 있어 정확도 기준으로 거를 수 있다. 예: 개정 附則 안의 모호한 엣지(`INTERNAL_PAT/amend_suppl`)를 제외.

### `law`, `pending`, `stats`

```bash
jlawcite law 個人情報保護法 --toc     # 현행 시행일, 개정 예정, 편·장·조 목차
jlawcite pending --until 20261231    # 기간 내 시행 예정 개정 전체
jlawcite pending --law 民法
jlawcite stats
```

---

## 3. JSON 출력 (`--json`)

| 명령 | 레코드 |
|---|---|
| `search` | `{node_id, law_id, article_id, section, heading, score, snippet[, body]}` (score = BM25, 작을수록 적합) |
| `get` | `{node, law, text, pending[], note?}` — `node`는 `nodes` 테이블 행, `law`는 `laws` 행 |
| `refs` | `{node, out: [edge…], in: [edge…]}` — edge = `{source, target, rel, raw, extracted_from, fallback_level, confidence, *_title, *_law_title}` |
| `law` | `{law, pending[], toc[]}` |
| `pending` | `{law_id, law_title, mst_id, enforcement_date, enforcement_note, amend_law_name, amend_law_num, amend_promulgation_date, supersedes_mst_id, url}` 행 |

---

## 4. Python API

```python
from pathlib import Path
from jlawcite.search import SearchDB, build_index, parse_citation

db = SearchDB(Path("data/search/jp_search.sqlite"))
db.lookup("民法第七百九条")["text"]
db.search("解雇 予告", law="労働基準法", limit=10)
db.search("退職金の課税", natural=True)
db.refs("322AC0000000049_a20", direction="in", rels=["CITES"])
db.pending(until="20261231")
db.resolve_law("独禁法")             # → laws 행
parse_citation("会社法第二条第一項第十二号の二")
```

SQLite 파일은 그대로 SQL로 조회할 수 있다(읽기 전용으로 열 것).

| 테이블 | 내용 |
|---|---|
| `laws` | law_id, title, promulgation_no, law_type, enforcement_date, is_active, next_enforcement_date, pending_version_count, mst_id |
| `law_names` | name → law_id, kind ∈ canonical / promulgation / abbrev / alias / old_name |
| `nodes` | 그래프 노드 전부 (id, type, law_id, parent_id, section, article_path, paragraph_num, item_path, suppl_tag, title, text, seq, suppl_amend_law_num) |
| `edges` | CITES / DELEGATES_TO / REFERS_TO_ATTACHMENT / AMENDS |
| `pending` | 미시행 개정 버전 |
| `chunks`, `chunks_fts` | 검색 청크와 FTS5 trigram 색인 |

---

## 5. 검색 기준선 (NTA 質疑応答事例)

국세청 질의응답사례 중 답변이 조문 단위로 해소된 1,170건을 평가셋으로 쓴다
(`data/parsed/jp_nta_gold.jsonl`, `pipeline/resolve_gold.py`). 질문문을 질의로, 답변이 근거로 든
조문(Article)을 정답으로 본다.

```bash
jlawcite eval --out docs/benchmarks/nta_retrieval_v3.2.json
```

| method | R@1 | R@5 | R@10 | R@20 | R@50 | MRR@50 | s/query |
|---|---:|---:|---:|---:|---:|---:|---:|
| bm25 (char-trigram OR) | 0.086 | 0.192 | 0.244 | 0.326 | 0.437 | 0.140 | 0.10 |
| bm25 + 1-hop citation graph | **0.256** | **0.403** | **0.459** | **0.500** | **0.550** | **0.325** | 0.11 |

(1,170 queries, e-Gov snapshot 2026-09-27, `docs/benchmarks/nta_retrieval_v3.2.json`)

- **bm25**: `search --nl`의 청크를 조문으로 묶고, 조문마다 처음 나온 순위를 쓴다.
- **bm25+graph**: 상위 20개 청크가 CITES로 가리키는 조문에 역순위 점수의 절반을 더한다(1-hop).
  예를 들어 施行令의 항이 검색되면 그 항이 인용한 모법 조문이 함께 올라온다.
- 임베딩 모델이나 학습 데이터를 쓰지 않는 기준선이다. dense·hybrid 검색과 비교할 때의 하한선으로 쓴다.

---

## 6. 한계

- **의미 검색이 아니다.** 동의어나 바꿔 쓴 표현(解雇 ↔ 雇止め)은 못 찾는다.
- **질의는 일본어여야 한다.** 한국어·영어 질의는 번역을 먼저 거쳐야 한다.
- **1–2자 검색어**는 색인을 쓰지 않아 느리다(수백 ms–수 초). 가능하면 3자 이상 검색어와 함께 쓴다.
- **현행 버전만 있다.** 개정 예정 본문은 `pending`의 URL·XML 경로로만 제공한다.
- **표·그림 본문**: 별표의 표(TableStruct) 셀 텍스트와 그림은 일부만 들어 있다.
- **인용 엣지 정확도**: `extracted_from`별 신뢰도가 다르다([GRAPH_SCHEMA_V2 §4.5](GRAPH_SCHEMA.md)).
