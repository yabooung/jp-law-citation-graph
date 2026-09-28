# 그래프 개선 가이드 (Developer Handbook)

**대상**: 이 리포에서 인용 해소율을 올리거나 신규 엣지를 추가하려는 개발자.
**전제**: `docs/GRAPH_SCHEMA.md` (스키마 SSOT), `docs/MIGRATION_v1_to_v2.md` (컨슈머 관점) 일독.

---

## 0. 5분 셋업

```bash
# 가상환경 + 개발 의존성
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 단위 테스트 — 전부 통과해야 시작 가능
python -m pytest tests/ -q

# 작은 샘플 ingest (검증 빠르게)
jlawcite build \
    --input <YOUR_EGOV_XML_DIR> \
    --csv  <YOUR_EGOV_XML_DIR>/all_law_list.csv \
    --output data/parsed_smoke --limit 200

# 통합 검증
jlawcite validate --data data/parsed_smoke
```

200 샘플은 30초 내 완료. 풀 코퍼스(8,998 laws)는 **~5분 (Pass 1+2)**.

미해소 인용을 문맥과 함께 보려면 `--dump-unresolved` → `jp_unresolved_cites.jsonl`
(`kind` ∈ internal / external_law / external_target / referential, `before`/`after` 문맥 포함).
§7의 1회용 스크립트보다 이 파일로 top-K 분석을 하는 것이 정확하다 (ingest와 동일한 로직).

---

## 1. 현재 KPI 스냅샷

v3.2 (2026-09-28, e-Gov 2026-09-27 스냅샷):

| 지표 | v3.0 | **v3.2** | 목표 |
|---|---|---|---|
| Internal 인용 해소 | 71.5% | **92.9%** | 90% ✅ |
| External 인용 해소 | 47.5% | **82.2%** | 60% ✅ |
| Referential 해소 | 74.1% | **92.2%** | 85% ✅ |
| Attachments per law | 0.28 | **2.40** | 0.5 ✅ |
| 본문 없는 법령 | 865 | **0** | 0 ✅ |

각 지표는 `data/parsed/jp_cites_stats.json`에서 실시간 측정. 작업 후 비교용.
KPI 분모에서 빠지는 항목(개정 전 법령·개정법 인용, 개정 附則 안의 인용)은
`docs/GRAPH_SCHEMA.md` §5 참조.

### 1.1 v3.2에서 배운 것 (다음 작업자에게)

- **KPI보다 먼저 유실을 본다.** 해소율이 낮던 원인의 상당 부분은 해소 로직이 아니라
  파서가 노드를 버린 것이었다(조문 없는 本則·附則, 분기 章·号). `jp_parse_stats.json`의
  `dup_ids`·`skipped`가 크면 KPI 작업 전에 원인부터 찾을 것.
- **해소율과 정확도는 따로 본다.** v3.0의 「法第N条」·「同条」·「附則第N条」는 상당수가
  *해소되었지만 틀린* 엣지였다. 규칙을 바꿀 때는 `extracted_from`별 표본을 문맥과 함께
  눈으로 확인한다(§7.6).
- **span은 정리된 이름에 맞춘다.** `LAW_NAME_PAT`이 절을 과포착하면 그 안의 前項·第N条가
  가려진다. §6.1의 "span trim 금지"는 *끝점* 이야기이며, 시작점은 정리된 이름 위치로 당긴다.

## 2. 어디부터 손댈까 (ROI 가이드)

| 순위 | 작업 | 예상 효과 | 시간 | 위험 |
|---|---|---|---|---|
| 1 | **同号/前各号 토큰 추가** | Referential +5~10%p | 1~2h | 낮음 |
| 2 | **alias 100개 → 500개 확장** | External +5~10%p | 3~5h (반자동 가능) | 낮음 |
| 3 | **Internal 미해소 top-K 분석** | Internal +5~15%p | 4~6h | 중간 |
| 4 | **AMENDS 패턴 보강** | AMENDS 60 → 1,000+ | 3~4h | 중간 |
| 5 | **Multi-version 그래프** | SUPERSEDES dangling 해결 | 1~2일 | 높음 |
| 6 | **Internal regex over-extract 정제** | Internal +5%p | 4~6h | 중간 |

> 1~2번이 **시간 대비 가장 큰 KPI 점프**. 여기부터 시작 권장.

---

## 3. 작업 시나리오별 진입점

### 3.1 새로운 referential 토큰 추가 (가장 쉬움)

목표: `同号`, `前各号`, `前項各号`, `前段`, `後段`, `本文`, `ただし書` 등 미구현 토큰 처리.

**수정 위치 3곳**:

1. `jlawcite/citation_extractor.py:50` — `REFERENTIAL_PAT` regex에 토큰 추가
2. `jlawcite/citation_resolver.py:resolve_referential()` — 토큰별 해소 분기 추가
3. `tests/test_citation_resolver.py` — 신규 토큰별 테스트 케이스

**예제** — `前項各号` 추가:
```python
# citation_extractor.py
REFERENTIAL_PAT = re.compile(
    r"(前条|次条|...|前項各号|前各号|各号)"
)

# citation_resolver.py — resolve_referential 내부
if kind in ("前項各号", "前各号"):
    # 직전 paragraph(또는 same paragraph)의 모든 Item 노드를 가리키는
    # 집계 엣지 1개 (raw 보존). LawContext에 item_ids_by_paragraph
    # 인덱스를 추가해야 함.
    ...
```

> Item 인덱스가 현재 `LawContext`에 없음 — 필요 시 `build_law_contexts`에 추가.

---

### 3.2 외부 인용 해소율 올리기 (alias 확장)

#### 3.2.1 진단 — 미해소 top-K 보기

```python
# 1회용 스크립트 (cookbook §7-1 참조)
python - <<'PY'
import json, sys
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
from jlawcite.citation import extract_external
from jlawcite.resolver import LawNameIndex, normalize_promulgation, load_aliases
from pathlib import Path

# Build name index from corpus
canonical, prom = {}, {}
text_records = []
for line in open('data/parsed/jp_nodes.jsonl', encoding='utf-8'):
    n = json.loads(line)
    if n['type'] == 'Law':
        canonical[n['title']] = n['id']
        if 'promulgation_no' in n:
            k = normalize_promulgation(n['promulgation_no'])
            if k: prom[k] = n['id']
    elif n['type'] in ('Paragraph', 'SupplParagraph', 'Item') and n.get('text'):
        text_records.append(n)

aliases = load_aliases(Path('src/jlawcite/jp_law_aliases.json'))
idx = LawNameIndex(canonical, prom, aliases)

import random; random.seed(42)
sample = random.sample(text_records, 50000)
unresolved = Counter()
for rec in sample:
    refs, _ = extract_external(rec['text'])
    for r in refs:
        if idx.resolve(r.law_name_raw, r.promulgation) is None:
            unresolved[r.law_name_raw] += 1

for n, c in unresolved.most_common(50):
    print(f'{c:>6}× {n!r}')
PY
```

#### 3.2.2 추가 위치

- **수동 alias**: `src/jlawcite/jp_law_aliases.json` — flat `{alias: canonical}` map
- **자동 alias 후보**: 진단 결과의 top-50 중 정식 법령명에 매칭되는 약칭

#### 3.2.3 alias 추가 후 검증

```bash
python -m pytest tests/test_citation_resolver.py -q  # 충돌 감지
jlawcite build ... --output data/parsed_test --limit 1000
jlawcite validate --data data/parsed_test  # KPI 비교
```

#### 3.2.4 의외로 자주 등장하는 패턴

진단 결과에서 자주 보이는 미해소 유형:
- `準用[법명]` — `準用` 접두어 → `_PREFIX_STRIP`에 이미 있음. 동작 확인.
- `〜の特例〜` — 약칭화 안 됨 → alias 추가 또는 suffix 인덱스 보강
- `〜法等〜` — 等 접미어 처리 필요

---

### 3.3 Internal 인용 해소율 올리기 (가장 어려움)

Internal 미해소(약 240k건)의 가능 원인 3가지:

#### 원인 A — Article 노드 emit 누락
일부 법령에서 Article 자체가 `article_index`에 없음. 진단:

```python
# pipeline 산출물에서 Article 카운트와 INTERNAL_PAT 매치 카운트 비교
import json
from collections import defaultdict
articles_per_law = defaultdict(int)
for line in open('data/parsed/jp_nodes.jsonl', encoding='utf-8'):
    n = json.loads(line)
    if n['type'] in ('Article', 'SupplArticle'):
        articles_per_law[n['law_id']] += 1
# 0건인 법령 찾기 — Article 없는데 Paragraph는 있는 케이스
for line in open('data/parsed/jp_nodes.jsonl', encoding='utf-8'):
    n = json.loads(line)
    if n['type'] == 'Law' and articles_per_law[n['id']] == 0:
        print(n['id'], n['title'])
```

> 이런 법령이 있다면 `xml_parser._walk_main`이 그 XML 구조를 못 따라가는 것. 해당 XML 직접 보고 패턴 추가.

#### 원인 B — Regex over-extract
`INTERNAL_PAT = 第({_NUM})条((?:の{_NUM})*)(?:第({_NUM})項)?(?:第({_NUM})号)?`

미해소 art_path top-K를 봐서 비정상적으로 큰 숫자가 자주 보이면 (`第999条` 등) 이는 본문의 다른 숫자가 잘못 잡힌 것. 패턴 정제 필요.

#### 원인 C — 정말로 그 조문이 없음
폐지된 조문, 이전 버전 조문 등을 본문에서 인용. 해소 불가능 — `unresolved.jsonl`에 남기는 것이 정답.

**진단 스크립트 (Cookbook §7-2)**.

#### 수정 위치
- `jlawcite/xml_parser.py:_walk_main` — Article 누락 케이스
- `jlawcite/citation_extractor.py:INTERNAL_PAT` — over-extract 정제
- `pipeline/ingest_full.py:_resolve_target` — fallback 단계 조정

---

### 3.4 신규 엣지 타입 추가 (예: REFERS_TO_FORM)

설계지침 §3.1을 먼저 갱신해야 함 (SSOT 원칙 P1).

**5단계**:

1. `docs/GRAPH_SCHEMA.md` §3.1 표에 새 rel 추가
2. `jlawcite/schemas.py:JpEdgeRel` Literal에 추가
3. `jlawcite/citation_extractor.py` — 패턴 + dataclass + extract_* 함수
4. `pipeline/ingest_full.py` — Pass 2에 추출/해소/dedup, 별도 `jp_*_edges.jsonl` 산출
5. `pipeline/validate.py:v06_enum_usage` 자동 반영 — 별도 작업 불필요

테스트는 `tests/test_citation.py` + `tests/test_validate.py`에 추가.

---

### 3.5 노드 타입 추가 (예: Subitem)

**중요**: 노드 타입 추가는 ID 규칙·인덱스·검증 모두 영향. 설계지침 §2 갱신 후 진행.

**6단계**:

1. `docs/GRAPH_SCHEMA.md` §2.1 / §2.2 갱신
2. `jlawcite/ids/normalize.py` — `make_*_key`, `parse_article_key`, `ARTICLE_KEY_RE` 갱신
3. `jlawcite/schemas.py:JpNodeType` + `GraphNode` validator
4. `jlawcite/xml_parser.py` — emit 함수 추가 (`_emit_subitem` 등)
5. `pipeline/ingest_full.py` — `article_index` 키 확장, 적합한 src/target 분류
6. `pipeline/validate.py:v06` 자동 반영, 필요 시 v01 재테스트

---

## 4. 핵심 파일 맵

| 파일 | 줄 수 | 무엇을 하나 | 자주 손대는 부분 |
|---|---|---|---|
| `jlawcite/citation_extractor.py` | ~330 | 인용 표현 → 추상 ref 객체 | 정규식 패턴, dataclass |
| `jlawcite/citation_resolver.py` | ~280 | ref → law_id / target node | alias 로직, prefix/suffix 매칭 |
| `jlawcite/xml_parser.py` | ~360 | e-Gov XML → ParsedRecord | 노드 emit, 텍스트 수집 |
| `jlawcite/ids/normalize.py` | ~190 | article_key 생성/검증 | ID 규칙 변경 시 |
| `jlawcite/schemas.py` | ~250 | Pydantic 모델 (v2 + v1 legacy) | 신규 타입/엣지 |
| `jlawcite/numerals.py` | ~70 | 漢数字 ↔ int | 수자 표기 신규 케이스 |
| `pipeline/ingest_full.py` | ~410 | 두-패스 통합 파이프라인 | 인덱스, Pass 2 로직 |
| `pipeline/validate.py` | ~280 | V01–V10 검증 | 신규 검사 추가 |
| `pipeline/build_versions.py` | ~70 | SUPERSEDES 별도 산출 | CSV 컬럼 변경 시 |
| `src/jlawcite/jp_law_aliases.json` | — | 손수 alias 70+ | 신규 alias 추가 |

---

## 5. 측정·검증 워크플로

### 워크플로 A — 단위 테스트만 (코드 수정 후 즉시)
```bash
python -m pytest tests/ -q
```
1초 내. 회귀 빠르게 잡힘.

### 워크플로 B — 작은 샘플 통합 테스트 (인용 로직 수정 후)
```bash
jlawcite build --input <XML_DIR> --output data/parsed_smoke --limit 500
jlawcite validate --data data/parsed_smoke
cat data/parsed_smoke/jp_cites_stats.json
```
~30초. KPI 변화 빠르게 확인.

### 워크플로 C — 풀 코퍼스 (큰 변경 후)
```bash
jlawcite build --input <XML_DIR> --csv <CSV> --output data/parsed
jlawcite validate --data data/parsed
```
~3분 (Pass 1 ~30s, Pass 2 ~2.5min).

### 워크플로 D — 결정성 비교 (회귀 의심 시)
```bash
# 1회차
jlawcite build ... --output data/parsed_a
sha=$(jlawcite validate --data data/parsed_a 2>&1 | grep sha256)

# 2회차 — 같은 명령
jlawcite build ... --output data/parsed_b
sha2=$(jlawcite validate --data data/parsed_b 2>&1 | grep sha256)

[ "$sha" = "$sha2" ] && echo "deterministic ✓" || echo "NON-DETERMINISTIC"
```
정렬·순서 안정성 깨졌다는 신호.

---

## 6. 함정 (자주 실수하는 것)

### 6.1 regex 변경 시 mask_spans 일관성
`extract_external`은 매칭된 span을 반환해서 `extract_internal`이 중복 카운트하지 않도록 함. external 패턴 바꿀 때 span 끝점을 정확히 유지.

```python
spans.append((m.start(), m.end()))  # 절대 trim하지 말 것
```

### 6.2 article_index 키 변경 = Pass 2 전체 영향
`(law_id, art_path, pnum, inum)` 4-tuple 구조가 v2의 specificity-aware 매칭 핵심. 키 형식 바꾸려면 `_resolve_target`도 동기화.

### 6.3 LAW_NAME_PAT lazy quantifier
```python
LAW_NAME_PAT = r"([一-鿿々ヶ぀-ゟ、]{1,40}?(?:法|令|...))"
                                       ^ lazy
```
greedy(`+`)로 바꾸면 over-capture 폭증. 절대 금물.

### 6.4 결정성 깨뜨리기
- `dict` 순회 (Python 3.7+ insertion order 보장이지만, set은 불안정)
- `os.listdir` 정렬 미보장 → `sorted()` 필수
- 병렬화 시 결과 순서 보장 필요

V08 hash 변경 = 결정성 깨졌다는 신호.

### 6.5 ID 형식 변경
`make_article_key` / `make_attachment_key` / `make_hierarchy_key` 출력 변경 시:
- `ARTICLE_KEY_RE` 동기화 (안 하면 `validate_article_key` fail)
- `parse_article_key` 역연산 동기화
- 기존 `article_index` 키 호환 여부 검토

### 6.6 SupplArticle/SupplParagraph emit 빠뜨리기
새 엣지 타입 추가 시 source 후보를 `_TEXT_BEARING = {"Paragraph", "SupplParagraph", "Item"}`에 SupplArticle/SupplParagraph 포함 여부 확인.

### 6.7 family_index suffix 매칭의 한계
`_FAMILY_SUFFIX_TO_KIND`는 `'施行令'`, `'施行規則'` 등 단순 suffix 매칭. 「○○法律施行令」 (令이 法律 뒤에) 같은 변형은 안 잡힘. 가족 매핑 정확도가 떨어지면 여기 보강.

---

## 7. 진단 스크립트 cookbook

### 7.1 미해소 외부 인용 top-K
§3.2.1 참조.

### 7.2 미해소 내부 인용 top-K (어느 art_path가 미해소인가)
```python
import json, sys
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
from jlawcite.citation import extract_internal, extract_external

article_index = {}  # (law_id, art_path) → True
for line in open('data/parsed/jp_nodes.jsonl', encoding='utf-8'):
    n = json.loads(line)
    if n['type'] in ('Article', 'SupplArticle'):
        article_index[(n['law_id'], n['article_path'])] = True

unresolved = Counter()  # (law_id, art_path)
text_records = [json.loads(l) for l in open('data/parsed/jp_nodes.jsonl', encoding='utf-8')
                if json.loads(l)['type'] in ('Paragraph', 'SupplParagraph', 'Item')
                and json.loads(l).get('text')]

import random; random.seed(42)
for rec in random.sample(text_records, 50000):
    src_law = rec['law_id']
    _, spans = extract_external(rec['text'])
    for ir in extract_internal(rec['text'], mask_spans=spans):
        ap = '-'.join([str(ir.article_num)] + [str(e) for e in ir.eda]) \
             if ir.eda else str(ir.article_num)
        if (src_law, ap) not in article_index:
            unresolved[(src_law, ap)] += 1

for (lid, ap), cnt in unresolved.most_common(30):
    print(f'{cnt:>5}× {lid} 第{ap}条')
```

### 7.3 가장 인용된 법령 (인-디그리 분석)
```python
import json
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
target_laws = Counter()
for line in open('data/parsed/jp_cites_edges.jsonl', encoding='utf-8'):
    e = json.loads(line)
    target_laws[e['target'].split('_')[0]] += 1
for lid, c in target_laws.most_common(20):
    print(f'{c:>7}  {lid}')
```

### 7.4 Dangling 빠른 확인
```python
import json
nodes = {json.loads(l)['id'] for l in open('data/parsed/jp_nodes.jsonl', encoding='utf-8')}
for fp in ('jp_cites_edges.jsonl', 'jp_delegates_edges.jsonl', 'jp_attaches_edges.jsonl'):
    bad = sum(1 for l in open(f'data/parsed/{fp}', encoding='utf-8')
              if json.loads(l)['target'] not in nodes)
    print(f'{fp}: {bad} dangling')
```

### 7.6 규칙별 정확도 표본 (문맥 포함)
```python
import json, random
random.seed(0)
RULE = 'INTERNAL_PAT/enum_carryover'   # extracted_from 값
es = [json.loads(l) for l in open('data/parsed/jp_cites_edges.jsonl', encoding='utf-8')
      if RULE in l and random.random() < 0.001][:30]
src = {e['source'] for e in es}; txt = {}; title = {}
for l in open('data/parsed/jp_nodes.jsonl', encoding='utf-8'):
    n = json.loads(l)
    if n['id'] in src: txt[n['id']] = n['text']
    if n['type'] == 'Law': title[n['id']] = n['title']
for e in es:
    t = txt[e['source']]; k = t.find(e['raw'])
    print(f"[{title[e['target'].split('_')[0]]}] …{t[max(0, k-40):k]}【{e['raw']}】")
```

### 7.5 fallback_level 분포
```python
import json
from collections import Counter
c = Counter(json.loads(l).get('fallback_level', 'unknown')
            for l in open('data/parsed/jp_cites_edges.jsonl', encoding='utf-8'))
for k, v in c.items(): print(f'{v:>10,}  {k}')
```

---

## 8. 우선순위별 TODO

### 완료 (v3.2)
- [x] Internal 미해소 top-K 진단 → 구조 유실 패치 (조문 없는 本則·附則, 분기 章·号)
- [x] `同号 / 前号 / 次号 / 前各号` referential + `LawContext.item_ids_by_para`
- [x] 약칭 정의(以下「X」という。) 자동 수집 — alias 수동 확장 대신
- [x] 나열 이어받기, 同条 선행 인용, 本則/附則 스코프 인덱스

### P0 — 다음 작업으로 권장
- [ ] External 미해소(`external_law` ~11만): 조약·協定·告示 등 코퍼스 밖 문서 분리 집계,
      「昭和…年法律第N号」만 있고 법령명이 없는 인용(공포번호 단독) 해소
- [ ] 약칭 정의의 스코프(「この条において」「この項において」) 반영 — 현재는 법령 전체에 적용
- [ ] Referential 미해소(~3.8만) 분석 — 前条가 章 경계를 넘는 경우 등

### P1 — 가치 있지만 시간 더 듦
- [ ] AMENDS 패턴 보강 (현재 117건 → 1,000+ 목표)
- [ ] 読み替え 규정(「…中「A」とあるのは「B」」) 구조화 — 치환 대상 조문 엣지
- [ ] 정확도 평가셋: `extracted_from`별 200건 수기 라벨 → precision 수치화

### P2 — 큰 변경
- [ ] Multi-version ingest (현행 버전만 → `jp_pending_versions.jsonl`의 예정 본문까지 노드화, 조문 diff)
- [ ] Subitem(イ・ロ・ハ) 노드 추가
- [ ] 判例 노드 + `CITES_PRECEDENT` 엣지 (v2.1 스코프 — design doc §9 TBD)

### P3 — 운영 환경
- [ ] 증분 ingest (e-Gov diff 처리)
- [ ] Neo4j 적재 스크립트 (`pipeline/load_neo4j.py`)
- [ ] 데이터 drift 모니터링

---

## 9. 더 읽을거리

| 문서 | 역할 |
|---|---|
| `docs/GRAPH_SCHEMA.md` | 스키마 SSOT — 변경 시 먼저 갱신 |
| `docs/MIGRATION_v1_to_v2.md` | 컨슈머 영향 (변경 시 컨슈머에 미치는 파급) |
| `README.md` | 사용법 |
| `git log --oneline` | Phase별 변경 추적 |
| `pipeline/validate.py` | V01–V11 검사 — 새 검사 패턴 학습 |
| `tests/` | 단위 테스트 + `test_ingest_e2e.py`(2법령 미니 코퍼스로 v3.2 규칙 전체 검증) |

---

## 10. 작업 시작 전 최종 체크리스트

- [ ] `pytest` 전 테스트 통과 확인 (회귀 베이스라인)
- [ ] `git status` 깨끗 — 작은 단위로 커밋
- [ ] 변경 종류에 따라 어떤 워크플로(§5)로 검증할지 결정
- [ ] 큰 변경이면 설계지침 갱신 먼저 (P1 원칙)
- [ ] 결정성 깨질 가능성 점검 (§6.4)
- [ ] 작업 후 KPI 비교 (`data/parsed/jp_cites_stats.json` before/after)
