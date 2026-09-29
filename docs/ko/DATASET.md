# JLaw-CiteGraph 데이터셋 카드 (연구용 기록)

일본 현행 법령 전체(e-Gov 法令)를 조·항·호 단위 그래프로 만든 데이터셋과 그 생성 과정을 적는다.
재현, 인용, 한계 판단에 필요한 내용을 한곳에 모았다. 스키마의 세부 규칙은 [GRAPH_SCHEMA.md](GRAPH_SCHEMA.md),
검색도구는 [SEARCH.md](SEARCH.md), 해소율 개선 방법은 [IMPROVING_THE_GRAPH.md](IMPROVING_THE_GRAPH.md)에 있다.

| 항목 | 값 |
|---|---|
| 데이터셋 버전 | v3.2 (그래프 스키마 v2.0, 검색 DB search-v1) |
| 원천 스냅샷 | e-Gov 法令 일괄 다운로드 `all_xml.zip`, CSV 타임스탬프 2026-09-27 15:03 JST |
| 기준일 (`--as-of`) | 2026-09-29 — 이날 시행 중인 버전 |
| 범위 | 法律 2,078 · 政令 2,334 · 府省令·規則 4,508 · 勅令 69 · 太政官布告·達 9 = **8,998 법령** |
| 기간 | 明治 5년(1872) ~ 令和 (e-Gov 수록 현행 법령 전체) |
| 언어 | 일본어 (원문 그대로, NFKC 정규화 없음 — 검색 색인만 정규화) |
| 라이선스 | 코드 Apache-2.0 · 원천 데이터는 §7 |

---

## 1. 무엇이 들어 있나

### 1.1 노드

| 타입 | 수 | 본문 문자 수 | 설명 |
|---|---:|---:|---|
| Law | 8,998 | – | 법령. `enforcement_date`, `is_active`, `next_enforcement_date`, `pending_version_count`, `abbrevs`(공식 약칭) |
| Hierarchy | 26,664 | – | 編·章·節·款·目 |
| Article | 243,277 | – | 本則 조. 제목만 있고 본문은 하위 항에 있다 |
| Paragraph | 504,241 | 56.2M | 本則 항 |
| Item | 515,834 | 42.7M | 호 (イ·ロ·ハ 이하 세목은 호 본문에 평탄화) |
| SupplArticle | 240,053 | – | 附則 조 (블록마다 `suppl_tag`, 개정 附則은 `suppl_amend_law_num`) |
| SupplParagraph | 326,379 | 32.6M | 附則 항 |
| Attachment | 21,550 | 10.2M | 別表·様式·書式·別記·別図·付録 |
| **합계** | **1,886,996** | **141.7M** | |

### 1.2 엣지

| 관계 | 수 | 의미 |
|---|---:|---|
| CONTAINS | 1,877,998 | 구조 트리 (Law → Hierarchy → Article → Paragraph → Item). 루트 외 모든 노드는 부모가 정확히 1개 |
| CITES | 1,417,648 | 본문 인용. 법령 간 567,883 · 같은 법령 안 849,765 |
| DELEGATES_TO | 67,666 | 「政令で定める」 등 위임 → 하위 법령(법령 단위) |
| REFERS_TO_ATTACHMENT | 37,377 | 「別表第一」「様式第二」 참조 |
| AMENDS | 117 | 附則이 本則 조문을 개정 (패턴이 좁아 재현율이 낮음) |

CITES의 해소 방식(`extracted_from`) 분포:

| 해소 방식 | 수 | 뜻 |
|---|---:|---|
| `INTERNAL_PAT` | 309,325 | 같은 법령의 「第N条」 |
| `NAKED_LAW_PAT/defined_abbrev` | 200,120 | 법령 안에서 정의한 약칭 「法第N条」(以下「法」という。) |
| `REFERENTIAL/*` | 380,377 | 前項 112k · 同条 63k · 前各号 46k · 前条 45k · 同項 33k · … |
| `INTERNAL_PAT/amend_suppl` | 106,323 | 개정 附則 안의 「第N条」 (confidence 0.4, KPI 제외) |
| `INTERNAL_PAT/enum_carryover` | 89,847 | 나열 이어받기 「会社法第十条、第十一条」 |
| `EXTERNAL_FULL_PAT/*` | 264,751 | 법령명 명시: canonical 141k · promulgation 56k · defined_abbrev 46k · prefix_stripped 18k · … |
| `NAKED_LAW_PAT/same_as_last` 등 | 66,905 | 同法·新法·모법 family |

`fallback_level`: exact 1,382,838 · paragraph_to_article 17,704 (항을 못 찾아 조로 연결) ·
law_only 17,106 (同法·新法 단독 → 법령 노드).

### 1.3 부가 파일

| 파일 | 내용 |
|---|---|
| `jp_pending_versions.jsonl` | 기준일 이후 시행 예정인 개정 1,649건 (841법령): 시행일, 施行日備考, 개정법령명·번호·공포일, 직전 버전, e-Gov URL |
| `jp_cites_stats.json` | 해소 통계 전체 (KPI 분자·분모, 범위 밖 항목) |
| `jp_parse_stats.json` | 법령별 노드 수, `dup_ids`(1,733), `skipped`(19) |
| `jp_unresolved_cites.jsonl` | (`--dump-unresolved`) 미해소 인용 전부와 앞뒤 문맥 |
| `jp_nta_gold.jsonl` | 국세청 質疑応答事例 1,598건 (질문·답변·근거 조문, 2026-09-29 수집) — 1,186건이 조 단위 정답 보유 |

가장 많이 인용되는 법령 (다른 법령에서): 租税特別措置法 22,439 · 金融商品取引法 21,700 · 会社法 16,793 ·
地方税法 10,115 · 法人税法 9,001 · 保険業法 8,743 · 所得税法 8,503.

---

## 2. 생성 과정

```
e-Gov all_xml.zip ──fetch_egov──▶ data/raw/law_xml/{law_id}_{施行日}_{改正ID}/*.xml + all_law_list.csv
        │
        ▼ ingest_full --as-of YYYYMMDD
  버전 선택: 법령마다 施行日 ≤ as_of 중 최신 (이후 버전 → jp_pending_versions.jsonl)
        │
  Pass 1  XML → 노드·CONTAINS (xml_parser)
        │    - 인라인 마크업(Ruby·Sup·Sub·ArithFormula·QuoteStruct) 포함 전문 추출, Ruby 읽기(Rt) 제거
        │    - 조문 없는 本則·附則 → 가상 조문 '0', 분기 번호(章の二·号の二) 보존
        │
  Pass 1.5  이름 해소 자원: 법령명·공포번호·旧法令名·공식 약칭(LawTitle@Abbrev 3,165)·
        │    큐레이션 약칭·법령 내 약칭 정의(以下「X」という。16,818)·모법–施行令–施行規則 family
        │
  Pass 2  텍스트 노드마다 인용 추출 → 해소 → CITES / DELEGATES_TO / REFERS_TO_ATTACHMENT / AMENDS
        │
        ▼ validate (V01–V11)  →  search build (SQLite FTS5)
```

추출·해소 규칙은 [GRAPH_SCHEMA_V2 §4](GRAPH_SCHEMA.md)에 있다. 전부 규칙 기반(정규식 + 사전 + 문서 내 문맥)이며
학습 모델은 쓰지 않는다. 같은 입력이면 같은 출력이 나온다(V08 결정성 해시).

---

## 3. 품질

### 3.1 인용 해소율 (KPI, V07)

| 지표 | 해소 / 전체 | 비율 | 목표 |
|---|---:|---:|---:|
| 같은 법령 인용 (internal) | 302,262 / 325,347 | **92.9%** | 90% |
| 다른 법령 인용 (external) | 669,275 / 814,313 | **82.2%** | 60% |
| 지시어 (referential) | 486,903 / 527,858 | **92.2%** | 85% |

정확한 분자·분모는 `jp_cites_stats.json`에 있다. **분모에서 제외한 항목**(대상 본문이 코퍼스에 없거나 가리키는 대상이 모호함):

| 항목 | 이유 |
|---|---|
| `external_pre_amendment` | 「旧法第N条」「改正前の○○法」 — 개정 전 본문은 코퍼스에 없다 |
| `external_amending_law` | 「改正法第N条」 — 일부개정법 자체는 e-Gov 현행 법령에 수록되지 않는다 |
| `internal_amend_suppl_*` | 개정 附則 블록 안의 인용 — e-Gov가 개정 附則을 抄로만 수록한다 |
| `referential_self` | 本条·本項·各号 등 자기 참조나 수식어 |

### 3.2 정확도 (precision)

해소율은 "연결했는가"를 재고, 정확도는 "맞게 연결했는가"를 잰다. v3.2 평가에서는 규칙(`extracted_from`)별로
무작위 엣지를 뽑아 원문 문맥과 대상 조문을 대조했다. 총 180건이다. 오류가 나온 규칙은 수정한 뒤 20건을 새로 뽑아 다시 쟀다.

| 규칙 | 엣지 수 | 표본 정답 | 정확도 (95% Wilson) |
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
| `INTERNAL_PAT/amend_suppl` | 106,323 | 4/10 | 40% (17–69) — KPI 제외, confidence 0.4 |

¹ 20건 모두 법령은 맞았다. 다만 canonical 3건, prefix_stripped 5건은 개정 전 본문을 가리킨다(「旧○○法」「改正前の○○法」). 그래프에는 현행 버전만 있으므로 이런 엣지 16,311개에 `version: "pre_amendment"`와 confidence 0.7을 붙였다.

- 표본을 뽑은 13개 규칙(amend_suppl 제외)이 CITES의 86%를 차지한다. 엣지 수로 가중한 정확도 추정치는 **약 98%**다.
  amend_suppl까지 넣으면 약 93%다.
- 표본이 작아 규칙별 구간이 넓다(10건 전부 정답이어도 하한 72%). 판정은 개발 과정의 일부로 이루어졌고
  독립 평가자가 한 것이 아니다. 논문 수치로 쓰려면 독립 라벨링이 필요하다.
- 평가 중 발견해 고친 오류: 同条가 前項을 선행 인용으로 삼던 문제(5/10 → 17/20), 抄 附則에서 前条가 번호가 떨어진 조문을
  가리키던 문제(8/10 → 20/20), 공동 부령 공포번호(「運輸省・建設省令」) 미인식, 「…に関する省令」을 bare 「省令」 토큰으로 자르던 문제,
  同法이 施行令을 가리키던 문제(종류 일치 검사 추가).
- 남은 오류 유형: 読み替え 인용문(「…中「第X条」」) 안의 조문 번호, 개정법 附則을 가리키는 同条, 旧法 뒤의 同条.

정밀도가 중요한 용도라면 다음 기준으로 거른다.

- `extracted_from`에서 `INTERNAL_PAT/amend_suppl`(confidence 0.4) 제외
- `fallback_level == "exact"`
- 필요하면 `REFERENTIAL/旧法` 등 `law_only` 엣지 제외

### 3.3 v3.0 → v3.2에서 고친 결함 (이전 버전 사용자 참고)

| 결함 | 영향 (v3.0) |
|---|---|
| 조문 없는 本則·附則 누락 | 본문이 전혀 없던 법령 865개, 附則 블록의 약 60% 유실 |
| 분기 章(第一章の二)이 앞 章과 충돌 | 해당 章 아래 조문 전체 유실 |
| 분기 号(第十二号の二) 충돌 | 호 약 4만 건 유실 |
| 인라인 마크업 뒤 본문 절단 | 약 5.4만 문장, 144만 자 유실 (Ruby·수식·위첨자) |
| 「法第N条」·「同法第N条」를 같은 법령으로 해소 | 다른 법령 인용이 자기 법령의 같은 번호 조문에 **잘못 연결** (추정 약 8만 건) |
| 「同条」가 항상 자기 조문 | 선행 인용 조문이 아니라 자기 조문으로 연결 |
| 「附則第N条」를 本則에서 조회 | 本則 같은 번호 조문에 잘못 연결 |
| 버전 선택 | 施行日을 和暦 문자열로 비교해 841법령에서 임의 버전 선택 |

---

## 4. 알려진 한계와 편향

- **현행법 스냅샷이다.** 기준일에 시행 중인 버전 하나만 노드로 만든다. 개정 이력은 없고, 시행 예정 개정은 메타데이터로만 제공한다.
- **개정법·폐지법은 없다.** e-Gov 현행 법령 DB의 범위 그대로다. 一部改正法 본문, 폐지된 법령, 조약 본문 대부분이 빠져 있어 그쪽을 향한 인용은 해소되지 않는다.
- **판례·통달(通達)은 없다.** NTA 골드셋에서도 基本通達 인용은 외부(EXTERNAL)로만 남는다.
- **세목(イ·ロ·ハ)은 노드가 아니다.** 호 본문에 평탄화되어 있어 「第三号イ」 인용은 호로 연결된다.
- **표 본문은 일부만 들어 있다.** 별표 안 표 셀의 텍스트는 들어 있지만 표 구조는 없다. 그림은 파일 경로만 남는다.
- **약칭 정의의 범위.** 「この条において「X」という」처럼 범위가 한정된 정의도 법령 전체에 적용한다. 드물게 오연결이 생길 수 있다.
- **도메인 편향.** 인용 밀도는 세법·금융법·회사법에 치우쳐 있다(§1.3). NTA 골드셋은 세법 한 분야다.
- **DELEGATES_TO는 법령 단위다.** 위임받은 구체 조문까지 연결하지 않는다.

---

## 5. 재현

```bash
git clone <repo> && cd JLaw-CiteGraph
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
python -m pytest -q                                              # 172 tests
jlawcite fetch --output data/raw/law_xml          # ~320MB, _snapshot.json에 수집 시각 기록
jlawcite build --input data/raw/law_xml \
    --csv data/raw/law_xml/all_law_list.csv --output data/parsed \
    --as-of 20260929 --dump-unresolved                           # ~5분
jlawcite validate --data data/parsed                   # V01–V11
jlawcite index                                  # ~1.5분, 2.6GB
jlawcite eval                                   # NTA 검색 기준선
```

- e-Gov는 스냅샷을 계속 갱신한다. 같은 결과를 얻으려면 **같은 `all_xml.zip`**을 보관해 `fetch_egov --zip`으로 풀고, **같은 `--as-of`**를 쓴다.
- 결정성: 같은 입력이면 V08 해시(정렬된 노드 줄의 sha256)가 같다.
- 실행 환경: Python 3.12, SQLite 3.49 (FTS5 trigram에는 3.34 이상 필요), Windows 11 / Linux. 전체 과정에 메모리 약 8GB.
- `resolve_gold`(NTA 골드셋 재생성)에는 NTA 수집본(사례당 한 줄 JSONL: id·zeimu·url·title·shokai·kaito·kankeihrei)이 필요하다. `eval/v2/nta_gold.jsonl`은 2026-09-29 수집본(1,598건)에 `resolve_gold`를 돌린 결과와 바이트 단위로 같다.

---

## 6. 검색 기준선

[SEARCH.md §5](SEARCH.md) 참조. 임베딩 없이 BM25만 쓴 기준선과, 인용 그래프 1-hop 확장을 비교한다.

---

## 7. 라이선스와 출처 표시

- **코드**: Apache License 2.0 (`LICENSE`).
- **법령 본문**: 일본 저작권법 제13조에 따라 법령은 저작권의 목적이 되지 않는다. e-Gov 法令検索의 법령 데이터는 특별한 이용 제한 없이 2차 이용이 허용된다. 다만 디지털청과 각 부처는 이용으로 생긴 불이익에 책임지지 않는다.
  권장 표기: 「出典：e-Gov法令検索（https://laws.e-gov.go.jp/）のデータを加工して作成」.
- **NTA 質疑応答事例** (`jp_nta_gold.jsonl`): 국세청 홈페이지 이용규약(政府標準利用規約 기반)에 따른다. 이용할 때는 「出典：国税庁ホームページ（該当ページURL）」를 적고, 편집·가공했다면 그 사실을 함께 적는다.
- 이 데이터셋은 법률 자문이 아니다. 법적 판단에는 반드시 관보·e-Gov 원문을 확인한다.

### 인용

```bibtex
@software{openlaw_jp,
  title   = {JLaw-CiteGraph: A citation graph and search index for Japanese statute law},
  version = {3.2},
  year    = {2026},
  note    = {e-Gov snapshot 2026-09-27, as-of 2026-09-29; Apache-2.0}
}
```
