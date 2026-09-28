# JLaw-CiteGraph Graph Schema v2.0 — 설계지침

**Status**: Draft (2026-04-28)
**Supersedes**: v1.0 (현재 `data/parsed/jp_*.jsonl`)
**Audience**: 본 리포 기여자, 산출물 컨슈머(연구용 로더), Qdrant/Neo4j 적재 스크립트 작성자

---

## 0. 목적

v1.0 그래프의 정합성 결함을 제거하고, "완벽한 데이터"의 정의를 명시적 KPI로 락인한다.
이 문서는 schema·extractor·ingest·검증 스위트의 **단일 진실 원본(SSOT)**이다.
구현은 이 문서를 위반할 수 없다 — 위반 시 문서를 먼저 갱신한다.

---

## 1. 정합성 원칙 (Principles)

| ID | 원칙 | 의미 |
|----|------|------|
| **P1** | 스키마 = 산출 | `schemas.py`에 정의된 enum·타입은 100% 실제로 emit되어야 한다. dead enum 금지. |
| **P2** | 손실 없는 인용 해소 | 인용의 specificity(条/項/号)는 보존 또는 명시적 강등(`fallback_level` 필드). 묵시적 강등(p3→p1) 금지. |
| **P3** | 단일 PK 규약 | 모든 노드 ID는 `validate_article_key` 또는 `LAW_ID_RE`를 통과해야 한다. 형식이 다른 ID 혼재 금지. |
| **P4** | 트리는 트리답게 | CONTAINS 그래프는 사이클 없는 DAG이며, 부모는 정확히 하나(루트 Law 제외). |
| **P5** | 결정론적 재생성 | 동일 입력 XML로 ingest 두 번 → 바이트 동일한 출력. 정렬·순서 안정성 보장. |

---

## 2. 노드 사양

### 2.1 타입 계층

v2에서는 **5종 노드**를 emit한다 (v1은 4종, 실제로는 2종만):

```
Law                         # 法令 자체
├── Part        (編)        # 선택 — XML에 존재 시
│   └── Chapter (章)
│       └── Section (節)
│           └── Subsection (款)  # 거의 없음
│               └── Article ◀─ 실질 인용 단위
│                   ├── Paragraph (項)
│                   │   └── Item (号)
│                   └── ...
└── Attachment              # 別表 / 様式 / 別記 (필요 시 자체 article_key)
```

**v2 노드 타입 enum** (`schemas.JpNodeType`):
```
Law | Article | Paragraph | Item | SupplArticle | SupplParagraph | Attachment | Hierarchy
```

> **v1과의 변경점**: Article과 Paragraph **분리**. v1은 Paragraph만 `Article`로 마스킹 — 이게 가장 큰 정합성 부채였다.

### 2.2 ID 규칙

| 노드 타입 | ID 패턴 | 예 |
|---|---|---|
| Law | `{law_id}` | `340AC0000000033` |
| Article | `{law_id}_a{art_path}` | `340AC0000000033_a10-2` |
| Paragraph | `{law_id}_a{art_path}_p{pnum}` | `340AC0000000033_a10-2_p3` |
| Item | `{law_id}_a{art_path}_p{pnum}_i{item_path}` | `340AC0000000033_a10-2_p3_i1`, `…_p1_i12-2` (第十二号の二) |
| SupplArticle | `{law_id}_asup-{tag}-{art_path}` | `340AC0000000033_asup-sp5-3` |
| SupplParagraph | `{law_id}_asup-{tag}-{art_path}_p{pnum}` | `340AC0000000033_asup-sp5-3_p1` |
| Attachment | `{law_id}_at-{kind}{annex_id}` | `340AC0000000033_at-1` (別表第一), `…_at-style-2` (様式第二) |
| Hierarchy | `{law_id}_h{level_code}{path}` | `340AC0000000033_hP1C2S1`, `…_hC1-2` (第一章の二) |

v3.2 규칙 (2026-09-28):

- **분기 번호**: 章/節/号의 `Num="1_2"`(…の二)는 `1-2`로 보존한다. 이전에는 `1`로
  잘려 앞 번호와 충돌했고, 충돌한 章의 하위 조문 전체와 分岐 号가 유실됐다.
  Item 노드의 `item_num`은 정수(12), `item_path`는 문자열(`"12-2"`)이다.
- **가상 조문 `0`**: `<Article>` 없이 `<Paragraph>`만 가진 本則·附則(짧은 法令·
  개정법 附則의 대부분)은 `art_path="0"`인 가상 Article(`synthetic: true`) 아래에 항을
  둔다. 제목은 本則이면 法令名, 附則이면 「附則」. 第0条는 실재하지 않아 충돌 없음.
  「附則第二項」 인용은 이 가상 조문의 항으로 해소된다.
- **附則 tag**: `sp{i}` (문서 내 SupplProvision 순번). `AmendLawNum`은 和暦 한자라
  영숫자 정규화 시 빈 문자열이 되므로 항상 `sp{i}`가 된다. 이전의
  `Extract="true"` → `"true"` fallback은 블록 간 충돌을 일으켜 제거했다.
  원문 `AmendLawNum`은 Suppl* 노드의 `suppl_amend_law_num` 필드에 보존하며,
  이 필드가 없는 첫 블록이 **제정 附則**이다.
- **Attachment kind prefix**: 別表 `""`, 様式 `style-`, 書式 `format-`, 別記 `note-`,
  別図 `fig-`, 別記(Notice) `notice-`, 付録 `appdx-`. 같은 법령의 別表第一과 様式第一이
  같은 ID로 충돌하던 문제 해결. 번호 없는 유일 첨부(「別表」「別記様式」)는 `0`.
  전각 숫자(様式第２)는 NFKC 정규화.

**`ARTICLE_KEY_RE`** (`ids/normalize.py`):
```python
ARTICLE_KEY_RE = re.compile(
    r"^[A-Za-z0-9]+"
    r"(?:"
    r"_a[A-Za-z0-9][A-Za-z0-9_-]*(?:_p\d+(?:_i\d+(?:-\d+)*)?)?"
    r"|_at-[A-Za-z0-9][A-Za-z0-9_-]*"
    r"|_h[A-Z][A-Za-z0-9_-]*"
    r")"
    r"(?:_add|_attachment|_DOC)?$"
)
```

### 2.3 노드 필드 (모든 타입 공통)

```python
class GraphNode:
    id: str                          # 위 규칙 (PK)
    type: JpNodeType                 # enum
    title: str                       # 표시용
    text: str = ""                   # 본문 (Paragraph/Item만 가짐)
    law_id: str                      # 모든 노드에 존재 (Law는 자기 자신)
    parent_id: str | None            # CONTAINS edge의 source — 명시적 저장
    section: Literal["main", "suppl"] = "main"

    # 위치 정보 (해당 타입에서만 의미)
    article_path: str | None         # '10' | '10-2'
    paragraph_num: int | None        # 1, 2, ...
    item_num: int | None             # 号 번호
    suppl_tag: str | None            # SupplProvision의 AmendLawNum 압축

    # 메타
    mst_id: str                      # 시행일_개정법령번호
    law_title: str                   # 법령명
    enforcement_date: str | None     # YYYYMMDD — 이 노드 버전의 施行日 (Law)
    promulgation_no: str | None      # 「昭和22年法律第26号」 정규형

    # 운영
    is_active: bool = True           # Law: --as-of 시점에 시행 중이면 True
    jurisdiction: Literal["JP"] = "JP"
    schema_version: Literal["v2.0"] = "v2.0"

    # Law 전용 (ingest 시 부여)
    pending_version_count: int       # --as-of 이후 施行 예정 버전 수
    next_enforcement_date: str | None  # 다음 개정 施行日 (YYYYMMDD)
```

**버전 선택 규칙**: 법령당 1개 버전만 노드화한다 — `ingest_full --as-of`(기본: 실행일) 시점에
시행 중인 버전(施行日 ≤ as_of 중 최신). 施行日은 디렉토리명 `{law_id}_{YYYYMMDD}_{改正法令ID}`에서
취한다(CSV 施行日은 和暦라 정렬 불가). 아직 한 번도 시행되지 않은 법령은 가장 이른 버전을
`is_active=False`로 넣는다. as_of 이후 버전은 노드화하지 않고 **`jp_pending_versions.jsonl`**에
메타데이터로 출력한다:

| 필드 | 설명 |
|---|---|
| `law_id`, `law_title` | 대상 법령 |
| `mst_id`, `enforcement_date` | 예정 버전 ID / 施行日 (YYYYMMDD). 2117 등은 e-Gov의 施行日 미정 placeholder |
| `enforcement_note` | 施行日備考 (예: 「公布の日から起算して一年を超えない範囲内において政令で定める日」) |
| `amend_law_name`, `amend_law_num`, `amend_promulgation_date` | 개정법령 |
| `supersedes_mst_id` | 직전 버전 (현행 또는 앞선 예정 버전) |
| `url`, `xml_relpath` | e-Gov 본문 URL / raw XML 상대경로 (예정 본문 파싱용) |

**v1 호환 필드는 컨슈머 마이그레이션이 끝날 때까지 병행 유지** (§8 참조).

---

## 3. 엣지 사양

### 3.1 엣지 enum과 정의역/공역

| `rel` | source 타입 | target 타입 | 의미 |
|---|---|---|---|
| `CONTAINS` | Law/Hierarchy/Article/Paragraph | 직계 자식 | 구조적 포함. 부모 정확히 1개. |
| `CITES` | Article/Paragraph/Item/SupplArticle | Article/Paragraph/Item/SupplArticle | 본문 내 인용. 동일/타 법령 무관. |
| `DELEGATES_TO` | Paragraph (上位法) | Article/Paragraph (下位法) | 「○○の規定により命令で定める」 위임. |
| `REFERS_TO_ATTACHMENT` | Paragraph/Item | Attachment | 「別表第N」 참조. |
| `SUPERSEDES` | Law (new mst_id) | Law (old mst_id) | 시계열 — **별도 파일** `jp_versions_edges.jsonl`. |
| `AMENDS` | SupplArticle (개정 부칙) | Article/Paragraph | 부칙이 본문을 수정한 관계. |

### 3.2 엣지 공통 필드

```python
class GraphEdge:
    source: str                  # 노드 id
    target: str                  # 노드 id
    rel: JpEdgeRel               # 위 enum

    # 메타데이터
    raw: str | None = None       # 원문 인용 문자열 (CITES/DELEGATES_TO만)
    fallback_level: Literal["exact", "paragraph_to_article",
                            "law_only", "promulgation_only"] = "exact"
    confidence: float = 1.0      # 0~1, 정규화 매칭 강도
    extracted_from: str | None = None  # 추출자 식별 (regex 패턴 ID 등)
```

**P2 핵심**: `fallback_level == "exact"`가 아닌 모든 CITES는 명시적으로 표시. 컨슈머가 필터링 가능.

---

## 4. 인용 해소 규칙

### 4.1 Specificity-aware 매칭

```
Item(号) > Paragraph(項) > Article(条) > Law
```

해소 알고리즘:
1. (law_id, art_path, pnum, item_num) 4-tuple 정확 매칭 시도
2. 실패 → (law_id, art_path, pnum) — `fallback_level="paragraph_to_article"` (Article 노드 가리킴, **p1로 강등 금지**)
3. 실패 → (law_id, art_path) — 같은 fallback 재사용
4. 실패 → (law_id) — `fallback_level="law_only"` (Law 노드 가리킴)
5. 실패 → 외부 promulgation_no만 알면 `fallback_level="promulgation_only"`로 외부 dangling 노드 생성 회피
6. 모두 실패 → `cites_unresolved.jsonl`에 기록 (소실 금지)

### 4.2 Referential refs 해소

`extract_referential` 결과는 **컨텍스트 의존**이므로 ingest 시점에 해소:

| 토큰 | 해소 |
|---|---|
| `前条` / `次条` | 같은 本則 또는 같은 附則 블록 안의 직전/직후 Article |
| `同条` | **같은 텍스트에서 가장 가까운 앞선 명시 인용**의 조문 (「第十条…同条第二項」). 앞선 인용이 없을 때만 현 Article |
| `同項` | 가장 가까운 앞선 인용의 항. 없으면 현 Paragraph |
| `同号` | 가장 가까운 앞선 인용의 호. 없으면 미해소 |
| `前項` / `次項` | 직전/직후 Paragraph |
| `前号` / `次号` | (출처가 Item일 때) 같은 항의 직전/직후 Item |
| `前各号` | (출처가 Item일 때) 같은 항의 앞선 Item 전부 — Item마다 엣지 1개 |
| `各号` | 수식어(「次の各号」「第一項各号」) — 엣지 미생성, `referential_self`로 집계 |
| `本条`, `本項`, `本法` … | 자기 자신 — 엣지 미생성 |
| `同法` / `新法` / `旧法` (조문 번호 없이 단독) | Law 노드 (`law_only`) |

토큰 뒤의 위치 표현(「同条第二項」「前条第一項第三号」)은 목표를 좁힌다.
v3.2 이전에는 `同条`가 항상 현 조문을 가리켰고, 附則 블록들이 한 시퀀스로 합쳐져
있었다. `--dump-unresolved` 로 미해소 목록을 `jp_unresolved_cites.jsonl`에 기록한다.

### 4.3 法令名 정규화

`law_name_to_id` 인덱스를 **3-key dictionary**로 확장:

```python
{
    "canonical": {"所得税法": "340AC0000000033", ...},      # LawTitle 정확 일치
    "alias":     {"所税法": "340AC0000000033", ...},         # 略称 — 외부 YAML 관리
    "promulgation": {"昭和40年法律第33号": "340AC...", ...}, # 法令番号 직접
}
```

`data/aliases/jp_law_aliases.yaml`을 신설 — 사람이 편집 가능. ingest 시 로드.
정규화 순서: promulgation → canonical → alias. **정확도 보존을 위해 alias 매칭에는 `confidence=0.9`**.

### 4.4 主-법령 ↔ 시행령/시행규칙 자동 링크

| 패턴 | 처리 |
|---|---|
| 「○○法施行令」 | 별도 노드 — `parent_law_id` 필드로 모법 연결 (CONTAINS 아님) |
| 「○○法施行規則」 | 동일 |
| 인용 시 모법명 + 「施行令」 결합어 | 단일 추출자에서 처리 |

→ **External 해소율 15% → ≥60%** 목표 (§5 KPI).

### 4.5 v3.2 해소 규칙 (2026-09-28)

**인덱스 스코프.** `article_index` 키는 `scope + (art_path, pnum, item_path)`이며
scope는 本則 `("M", law_id)` 또는 附則 블록 `("S", law_id, suppl_tag)`이다. 本則과
附則이 섞이지 않는다(이전: 本則에 없는 번호는 임의의 附則 조문으로 fallback).

**附則 인용.** 「附則第N条」: 本則·제정 附則 텍스트 → 제정 附則 블록, 개정 附則
텍스트 → 같은 블록. 「所得税法附則第N条」 → 대상 법령의 제정 附則.

**외부 법령명 해소 순서** (`ingest_full._resolve_ext_name`):
1. 출처 법령 자신의 약칭 정의 — 본문의 「…（…号。以下「法」という。）」를 Pass 1.5에서
   수집(`extract_abbrev_definitions`). 정의 대상이 개정 전 법령(「改正前の」, 旧-)이면
   `pre_amendment`, 해소되지 않는 一部改正法·整備法이면 `amending_law`로 표시.
2. 짧은 토큰 (`NAKED_LAW_PAT`, 앞 글자가 한자가 아닌 경우만):
   - `法`/`令`/`規則`/`省令`/`施行令`/`施行規則` → 모법·시행령 family (`anaphora_family`)
   - `同法`/`同令`/… → 같은 텍스트의 직전 외부 인용 법령 (`same_as_last`)
   - `新法`/`新令`/`新規則` → 토큰 종류가 출처와 같으면 출처 자신 (`amended_self`), 아니면 family
   - `旧法`/`旧令`/`旧規則` → `pre_amendment` (개정 전 본문은 코퍼스에 없음)
3. 전역 `LawNameIndex` (promulgation → canonical → old_name → alias → 접두 제거 → suffix).
   공포번호는 발령기관 수식을 허용한다(「平成十七年法務省令第十八号」).
4. 실패하고 이름이 개정법 형태면 `amending_law`, 아니면 `external_unresolved_law`.
5. **경계 가드** (JLaw-CiteGraph v1에서 이식): 과포착 정리(6.5)와 접미 일치(7)는 절·조사·버전
   경계에서만 자른다. 복합 법령명 중간(「失業|保険法」)에서는 자르지 않는다. 「旧○○法」「改正前の○○法」처럼
   개정 전 본문을 가리키는 인용은 현행 법령에 연결하되 `version: "pre_amendment"`와 confidence 0.7을 붙인다.

**과포착 정리.** `LAW_NAME_PAT`은 lazy지만 문장 앞부분을 잡는 경우가 있다
(「前項の規定は、法」). 이름 정리 후 **span 시작을 정리된 이름 위치로 당겨**
앞부분의 前項·第N条가 다른 추출기에 보이도록 한다. 「、法」「は法」처럼 절 끝의
짧은 토큰은 토큰만 남긴다.

**나열 이어받기** (`enum_carryover`). 「会社法第八百三十三条第二項、第八百三十四条」
「第百八十五条から第百八十七条まで」의 뒤 조문은 앞 인용의 법령·附則 여부를 이어받는다.
두 인용 사이가 `ENUM_GAP_PAT`(、及び並びに又は若しくはからまで, 괄호, 第N項/号/編/章,
前段·本文·ただし書, 끝의 中「)만으로 이루어질 때에 한한다. 앞 인용 법령이 미해소이거나
범위 밖이면 뒤 조문도 같은 분류로 집계한다(자기 법령으로 오연결하지 않음).

**개정 附則 안의 인용.** 개정법 附則 블록(`suppl_amend_law_num` 있음)의 인용은
KPI에서 제외하고 `internal_amend_suppl_*`로 따로 집계한다. 맨 「第N条」는 개정법 자신의
조문일 수 있어(표본 정확도 약 40%) 엣지에 `confidence: 0.4`, `extracted_from: INTERNAL_PAT/amend_suppl`을 단다.
「附則第N条」는 e-Gov가 개정 附則을 抄로만 수록해 대상이 없는 경우가 많다.

**`extracted_from` 값**: `EXTERNAL_FULL_PAT/{via}`, `NAKED_LAW_PAT/{via}`,
`INTERNAL_PAT`, `INTERNAL_PAT/enum_carryover`, `INTERNAL_PAT/amend_suppl`,
`REFERENTIAL/{token}`. `via` ∈ promulgation, canonical, old_name, alias,
prefix_stripped, suffix, anaphora_family, same_as_last, amended_self, defined_abbrev.

---

## 5. 데이터 품질 KPI

| 지표 | v1 실측 | v2 목표 | 측정 방법 |
|---|---|---|---|
| 노드 dangling 비율 | 측정 안 됨 | **0%** | CITES.target ∈ nodes |
| CONTAINS 트리성 | 미검증 | **사이클 0** | 위상 정렬 가능 |
| 스키마 enum 사용률 | 50% (4/8) | **100%** | grep enum vs 산출 |
| 내부 인용 해소 | 73% (641k/882k) | **≥90%** | resolved/total |
| 외부 인용 해소 | 15% (76k/512k) | **≥60%** | 동상 |
| Referential 해소 | 0% | **≥85%** | extract_referential 결과 vs 엣지 |
| Paragraph→Article 강등 비율 | 측정 안 됨 (silent) | **<10%, 모두 명시 표시** | fallback_level 통계 |
| ingest 결정성 | 미보장 | **diff 0 bytes** | 같은 입력 두 번 실행 |
| 별표 노드 | 0 | **법령당 평균 ≥0.5** | Attachment 노드 수 |
| DELEGATES_TO 엣지 | 0 | **≥10,000** | rel별 카운트 |

**v3.2 실측 (2026-09-28, e-Gov 2026-09-27 스냅샷)**: 내부 92.9% (302,262 / 325,347),
외부 82.2% (669,275 / 814,313), Referential 92.2% (486,903 / 527,858),
Attachment 21,550 (법령당 2.4), DELEGATES_TO 67,666, dangling 0.

KPI 분모 제외 항목(대상 본문이 코퍼스에 없거나 모호함): `external_pre_amendment`
(旧法第N条, 25,345), `external_amending_law` (改正法第N条, 44,184),
`internal_amend_suppl_*` (개정 附則 안의 인용, 295,023), `referential_self`
(本条·各号 등, 123,160). 모두 `jp_cites_stats.json`에 별도 수치로 남는다.

---

## 6. 검증 스위트

`pipeline/validate.py` 신규 — 모든 검사는 **종료 코드로 표현**.

| 검사 ID | 내용 | Severity |
|---|---|---|
| V01 | 모든 노드 id가 ARTICLE_KEY_RE 또는 LAW_ID_RE 통과 | FAIL |
| V02 | CONTAINS의 모든 source/target ∈ nodes | FAIL |
| V03 | CONTAINS 그래프 사이클 없음 | FAIL |
| V04 | 모든 비-Law 노드가 정확히 1개 부모 가짐 | FAIL |
| V05 | CITES.target ∈ nodes (dangling 0) | FAIL |
| V06 | enum 사용률 100% (각 type/rel ≥1건) | WARN |
| V07 | KPI 임계 미달 | WARN |
| V08 | 결정성: hash(sorted(nodes)) 안정 | FAIL |
| V09 | unresolved.jsonl + resolved 합 = 추출 총량 (소실 0) | FAIL |
| V10 | section 충돌 0건 (main/suppl 같은 키 없음) | FAIL |

CI에서 V01–V05, V08–V10이 FAIL이면 머지 차단.

---

## 7. 마이그레이션 단계

각 단계는 **독립적으로 머지 가능**해야 한다 (이전 단계 산출물 + 검증 스위트 통과).

### Phase 1 — Schema/Enum 정합 (코드만, 데이터 변경 없음)
- `schemas.py` v2 모델 추가, v1 모델은 `legacy.py`로 이동
- `JpNode.type`, `JpEdge.rel` enum을 §2.1 / §3.1로 갱신
- dead code (`Article`, `Addendum`, `Attachment` Pydantic 클래스)를 ingest에 실제 사용 OR 제거
- `validate_article_key` v2 패턴 적용
- 산출물: `schemas.py` 갱신, 단위 테스트
- **재ingest 불필요**

### Phase 2 — Article 노드 분리 (구조 변경, 재ingest 필요)
- `xml_parser._emit_article` → Article 노드 + 자식 Paragraph 노드 emit
- `_emit_item` 신설 → Item 노드 emit
- `_emit_hierarchy` 신설 → Part/Chapter/Section 노드 emit
- ingest_full에서 article_index를 4-tuple 키로 확장
- **재ingest 1회**, 검증 스위트 V01–V05 통과 확인

### Phase 3 — 인용 해소 강화 (재ingest 필요)
- specificity-aware 매칭 도입 (§4.1)
- `extract_referential` 통합, 컨텍스트 추적 (§4.2)
- `data/aliases/jp_law_aliases.yaml` 신설, 정규화 3-단 인덱스 (§4.3)
- 시행령/시행규칙 모법 연결 (§4.4)
- **재ingest 1회**, KPI ≥ 목표치 확인

### Phase 4 — 신규 엣지 (재ingest 부분)
- DELEGATES_TO 추출자 신설 (`citation_extractor.py` 추가 패턴)
- REFERS_TO_ATTACHMENT 추출자 + Attachment 노드 emit
- AMENDS 추출자 (부칙→본문)
- SUPERSEDES는 별도 스크립트 `pipeline/build_versions.py` (mst_id 분석)
- 산출물: `jp_delegates_edges.jsonl`, `jp_attaches_edges.jsonl`, `jp_amends_edges.jsonl`, `jp_versions_edges.jsonl`

### Phase 5 — 검증·CI
- `pipeline/validate.py` 작성, V01–V10 모두 통과
- pytest fixture 갱신 (작은 샘플 XML로 v2 형식 회귀 방지)
- pyproject.toml에 `JLaw-CiteGraph-validate` script 추가

### Phase 6 — 컨슈머 마이그레이션
- 컨슈머 로더 코드 변경
- v1 파일은 `data/parsed/legacy/`로 이동, v2가 default
- README의 schema 섹션 갱신

---

## 8. v1 호환

**호환 보장 기간**: Phase 6 머지 후 60일.

이 기간 동안:
- v1 파일(`jp_nodes.jsonl` 현행 형식)은 `pipeline/export.py` legacy 모드로 재생성 가능
- 신규 v2 파일은 v1 super-set: 모든 v1 필드 유지 + v2 신규 필드 추가
- v1 type 명명 (`Article`이 paragraph 노드를 가리킴)은 v2에서 `Paragraph` — 컨슈머 매핑표 제공

호환 deprecation 후:
- `legacy.py` 삭제
- `data/parsed/legacy/` 삭제
- 본 문서에서 §8 제거

---

## 9. 미정 사항 (TBD)

- **Imperial Order(勅令) 처리**: type code `DF`인 경우 act-like? 별도 분류? — 현재 `imperial_order`로 분리되나 인용에서 어떻게 표시되는지 샘플 분석 필요
- **判例 인용**: 향후 court decision 노드 도입 시 `CITES_PRECEDENT` 엣지 추가 — v2.1 스코프
- **Attachment 본문 텍스트화**: 別表가 PDF 임베드인 경우 — 일단 메타만 노드화, 본문은 별도 파이프라인

---

## 10. 변경 이력

| 버전 | 날짜 | 변경 |
|---|---|---|
| Draft | 2026-04-28 | 최초 작성 |
| v3.1 | 2026-09-28 | 현행 버전 선택(`--as-of`) + `jp_pending_versions.jsonl` + Law `enforcement_date`/`next_enforcement_date` |
| v3.2 | 2026-09-28 | 구조 유실 수정(조문 없는 本則·附則, 분기 章·号, 첨부 kind), 本則/附則 스코프 인덱스, 약칭 정의·짧은 토큰·나열 이어받기·同条 선행 인용 해소, span 정리, 인라인 마크업(Ruby·Sup·수식) 전문 추출, 공식 약칭(LawTitle@Abbrev → Law `abbrevs`), `--dump-unresolved` (§2.2, §4.2, §4.5) |
