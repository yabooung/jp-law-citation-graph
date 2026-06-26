"""Claude 라벨(_claude_labels_*.json) 집계 → via별 precision + Wilson CI + 코퍼스 가중 전체.
via별 코퍼스 엣지수로 가중. precision = O/(O+X), 모름(?) 제외."""
import json, math
from pathlib import Path

OUT = Path(__file__).resolve().parent
# 코퍼스 via별 외부엣지수 (build_precision_sample.py, fix 적용 후)
VIA_COUNT = {"canonical":791408,"promulgation":122625,"local_def_tail":204525,
             "local_def":85295,"alias":181,"suffix":2906,"old_name":1002,"prefix_stripped":885}

def wilson(o, n, z=1.96):
    if n==0: return (0,0)
    p=o/n; d=1+z*z/n
    c=(p+z*z/(2*n))/d; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return (max(0,c-h), min(1,c+h))

rows=[]
tot_o=tot_x=tot_q=0
wsum=0.0; wn=0
for f in sorted(OUT.glob("_claude_labels_*.json")):
    d=json.load(f.open(encoding="utf-8"))
    via=d["via"]; L=d["labels"].values()
    o=sum(1 for v in L if v=="O"); x=sum(1 for v in L if v=="X"); q=sum(1 for v in L if v=="?")
    n=o+x; prec=o/n if n else 0
    lo,hi=wilson(o,n)
    cnt=VIA_COUNT.get(via,0)
    rows.append((via,cnt,o,x,q,prec,lo,hi))
    tot_o+=o; tot_x+=x; tot_q+=q
    wsum+=cnt*prec; wn+=cnt   # 가중(모름 제외 via precision 사용)

rows.sort(key=lambda r:-r[1])
print("="*78)
print(f"{'via':16s}{'코퍼스엣지':>12s}{'O':>5s}{'X':>5s}{'?':>4s}{'precision':>11s}{'95% CI':>16s}")
print("-"*78)
for via,cnt,o,x,q,prec,lo,hi in rows:
    print(f"{via:16s}{cnt:>12,}{o:>5}{x:>5}{q:>4}{100*prec:>10.1f}%   [{100*lo:.0f}-{100*hi:.0f}%]")
print("-"*78)
samp_prec=tot_o/(tot_o+tot_x)
print(f"표본 단순평균 precision: {tot_o}/{tot_o+tot_x} = {100*samp_prec:.1f}%  (모름 {tot_q} 제외)")
print(f"코퍼스 가중 precision  : {100*wsum/wn:.2f}%")
print(f"  (alias 만 <100%; alias 코퍼스비중 {100*VIA_COUNT['alias']/wn:.1f}%)")
print("="*78)
