"""LLM(Claude) 라벨 vs 사람 blind 라벨 일치도 + Cohen's kappa 계산.
사용법: 사람이 precision_labeling.html 로 (제 라벨을 *안 본 채*) O/X 라벨 → precision_labeled.csv 다운로드.
그 CSV 경로를 인자로 주면 Claude 라벨(_claude_labels_*.json)과 대조해 agreement + kappa 출력.
  python compute_kappa.py <human_labeled.csv>
※ blind 성립 조건: 사람이 라벨할 때 Claude 판정을 보지 않았을 것. (spotcheck.html 은 Claude판정을
  보여주므로 blind 아님 → 반드시 labeling.html 사용.)
"""
import csv, json, sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
human_csv = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT/"precision_labeled.csv"
if not human_csv.exists():
    print(f"사람 라벨 CSV 없음: {human_csv}\n  precision_labeling.html 로 라벨 후 경로 지정.", file=sys.stderr); sys.exit(1)

# Claude 라벨: via별 {sample_index -> O/X}. 단 human CSV 는 row 순서로 라벨되므로
# via+row 로 매칭하려면 동일 샘플이어야 함. 여기선 human CSV 의 via 별 라벨 분포로 대조.
claude = {}
for f in OUT.glob("_claude_labels_*.json"):
    d = json.load(f.open(encoding="utf-8")); claude[d["via"]] = d["labels"]

rows = list(csv.DictReader(human_csv.open(encoding="utf-8-sig")))
# human CSV 는 via 순 정렬(build_precision_sample 순서) 가정 → via별 인덱스 재구성
from collections import defaultdict, Counter
by_via_rows = defaultdict(list)
for r in rows:
    by_via_rows[r["via"]].append(r)

pairs = []  # (claude, human) in {O,X}; 모름/공백 제외
for via, rs in by_via_rows.items():
    labs = claude.get(via, {})
    for i, r in enumerate(rs):
        h = (r.get("label_O_X") or r.get("label_O_X_H") or "").strip().upper()
        c = labs.get(str(i), "")
        if h in ("O","X") and c in ("O","X"):
            pairs.append((c, h))

if not pairs:
    print("대조 가능한 (Claude,사람) 쌍 0 — human CSV 라벨/순서 확인.", file=sys.stderr); sys.exit(1)

n=len(pairs); agree=sum(1 for c,h in pairs if c==h)
po=agree/n
# Cohen's kappa
cc=Counter(c for c,_ in pairs); ch=Counter(h for _,h in pairs)
pe=sum((cc[k]/n)*(ch[k]/n) for k in ("O","X"))
kappa=(po-pe)/(1-pe) if (1-pe) else 1.0
print(f"대조쌍(O/X, 모름 제외): {n}")
print(f"agreement(일치율) = {agree}/{n} = {100*po:.1f}%")
print(f"Cohen's kappa = {kappa:.3f}  ({'almost perfect' if kappa>0.8 else 'substantial' if kappa>0.6 else 'moderate' if kappa>0.4 else 'fair/poor'})")
# 불일치 상세
dis=[(via,i) for via,rs in by_via_rows.items() for i,r in enumerate(rs)
     if (r.get('label_O_X') or '').strip().upper() in ('O','X')
     and claude.get(via,{}).get(str(i)) in ('O','X')
     and (r.get('label_O_X') or '').strip().upper()!=claude.get(via,{}).get(str(i))]
print(f"불일치 {len(dis)}건: {dis[:20]}")
