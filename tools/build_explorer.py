"""Build the single-file interactive explorer (explorer.html) from data/.

    python tools/build_explorer.py

Reads data/laws.csv, data/cites_law_to_law.csv and data/release_stats.json;
embeds every law→law link so the page needs no server.
"""
import csv
import json
from pathlib import Path

REL = Path(__file__).resolve().parents[1]
laws = list(csv.DictReader((REL / "data" / "laws.csv").open(encoding="utf-8")))
stats = json.loads((REL / "data" / "release_stats.json").read_text(encoding="utf-8"))
id2i = {r["law_id"]: i for i, r in enumerate(laws)}
names = [r["name"] for r in laws]
types = [r["type"] for r in laws]
nexts = [r.get("next_enforcement_date", "") for r in laws]
edges = []  # [srcIdx, tgtIdx, w]
for r in csv.DictReader((REL / "data" / "cites_law_to_law.csv").open(encoding="utf-8")):
    s = id2i.get(r["src_law_id"]); t = id2i.get(r["tgt_law_id"])
    if s is None or t is None:
        continue
    edges.append([s, t, int(r["n_citations"])])
data = {"names": names, "types": types, "next": nexts, "edges": edges}
print(f"laws={len(names)} edges={len(edges)}")

HTML = r"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JLaw-CiteGraph Explorer — 日本法令 引用グラフ</title>
<style>
 :root{--bg:#0d1117;--pan:#161b22;--bd:#30363d;--fg:#e6edf3;--mut:#8b949e;--acc:#58a6ff;--out:#3fb950;--in:#d29922}
 *{box-sizing:border-box}html,body{height:100%;margin:0}
 body{font-family:'Segoe UI','Hiragino Kaku Gothic ProN',sans-serif;background:var(--bg);color:var(--fg);display:flex;flex-direction:column}
 header{padding:10px 18px;border-bottom:1px solid var(--bd);background:#0a0d12}
 h1{font-size:17px;margin:0}h1 small{color:var(--mut);font-weight:400;font-size:12px}
 .wrap{flex:1;display:grid;grid-template-columns:300px 1fr 300px;gap:0;min-height:0}
 .col{overflow:auto;padding:12px 14px}.col.mid{border-left:1px solid var(--bd);border-right:1px solid var(--bd);display:flex;flex-direction:column}
 input{width:100%;padding:8px 10px;background:#0d1117;border:1px solid var(--bd);border-radius:7px;color:var(--fg);font-size:14px}
 .sect{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;margin:14px 0 6px}
 .item{padding:6px 8px;border-radius:6px;cursor:pointer;font-size:13px;line-height:1.4;display:flex;justify-content:space-between;gap:8px}
 .item:hover{background:#21262d}.item .w{color:var(--mut);font-variant-numeric:tabular-nums}
 .center{text-align:center;padding:10px}.center .nm{font-size:20px;font-weight:700;margin:4px 0}.center .ty{color:var(--mut);font-size:12px}
 svg{width:100%;flex:1;min-height:0}
 .lbl{font-size:11px;fill:var(--fg)} .node{cursor:pointer}
 .hint{color:var(--mut);font-size:12px;line-height:1.6}
 a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
 .badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;border:1px solid var(--bd);color:var(--mut)}
 .out{color:var(--out)}.in{color:var(--in)}
 mark{background:#1f6feb55;color:#fff;border-radius:3px}
</style></head><body>
<header><h1>JLaw-CiteGraph Explorer <small>— 日本法令 引用グラフ · __NLAWS__法令 / __NPAIRS__ 法令間リンク · e-Gov __SNAP__ · v2</small></h1></header>
<div class="wrap">
 <div class="col" id="left">
   <input id="q" placeholder="法令名で検索 (例: 民法, 個人情報)" autocomplete="off">
   <div class="sect">検索結果</div><div id="results"></div>
   <div class="sect">被引用ハブ TOP</div><div id="hubs"></div>
 </div>
 <div class="col mid">
   <div class="center" id="center"><div class="hint">左で法令を選ぶと、その<b class="out">引用先</b>と<b class="in">被引用元</b>が表示されます。</div></div>
   <svg id="ego" viewBox="0 0 600 460"></svg>
 </div>
 <div class="col" id="right"></div>
</div>
<script>
const D=__DATA__;
const N=D.names.length;
// adjacency
const out=Array.from({length:N},()=>[]), inc=Array.from({length:N},()=>[]);
for(const [s,t,w] of D.edges){ out[s].push([t,w]); inc[t].push([s,w]); }
for(const a of out) a.sort((x,y)=>y[1]-x[1]);
for(const a of inc) a.sort((x,y)=>y[1]-x[1]);
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
// hubs by in-degree (distinct citers)
const hub=[...Array(N).keys()].map(i=>[i,inc[i].length]).sort((a,b)=>b[1]-a[1]).slice(0,30);
document.getElementById('hubs').innerHTML=hub.map(([i,c])=>
  `<div class="item" onclick="sel(${i})"><span>${esc(D.names[i])}</span><span class="w">${c}</span></div>`).join('');

const q=document.getElementById('q');
q.addEventListener('input',()=>{
  const v=q.value.trim(); const res=document.getElementById('results');
  if(!v){res.innerHTML='';return;}
  const hits=[];
  for(let i=0;i<N&&hits.length<60;i++) if(D.names[i].includes(v)) hits.push(i);
  hits.sort((a,b)=>inc[b].length-inc[a].length);
  res.innerHTML=hits.map(i=>`<div class="item" onclick="sel(${i})"><span>${esc(D.names[i]).replace(v,'<mark>'+v+'</mark>')}</span><span class="w">${inc[i].length}</span></div>`).join('')||'<div class="hint">該当なし</div>';
});

function listHtml(title,cls,arr){
  if(!arr.length) return `<div class="sect">${title}</div><div class="hint">なし</div>`;
  return `<div class="sect">${title} (${arr.length})</div>`+arr.slice(0,25).map(([i,w])=>
    `<div class="item" onclick="sel(${i})"><span class="${cls}">${esc(D.names[i])}</span><span class="w">${w}</span></div>`).join('');
}
function sel(i){
  document.getElementById('center').innerHTML=
    `<div class="ty">${esc(D.types[i])}</div><div class="nm">${esc(D.names[i])}</div>
     <div><span class="badge out">引用先 ${out[i].length}</span> <span class="badge in">被引用 ${inc[i].length}</span>${D.next[i]?` <span class="badge">次回改正 ${D.next[i].slice(0,4)}-${D.next[i].slice(4,6)}-${D.next[i].slice(6)}</span>`:''}</div>`;
  document.getElementById('left-extra')?.remove();
  document.getElementById('results').innerHTML=listHtml('この法令が引用する法令','out',out[i]);
  document.getElementById('right').innerHTML=listHtml('この法令を引用する法令','in',inc[i]);
  q.value='';
  drawEgo(i);
}
function drawEgo(i){
  const svg=document.getElementById('ego'); const W=600,H=460,cx=W/2,cy=H/2;
  const O=out[i].slice(0,8), I=inc[i].slice(0,8);
  const trunc=s=>s.length>14?s.slice(0,13)+'…':s;
  let g='';
  function spoke(arr,x0,sign){
    arr.forEach(([j,w],k)=>{
      const y=60+k*(H-120)/Math.max(1,arr.length-1||1);
      g+=`<line x1="${cx}" y1="${cy}" x2="${x0}" y2="${y}" stroke="${sign>0?'#3fb95066':'#d2992266'}" stroke-width="${Math.min(4,1+Math.log(w))}"/>`;
      g+=`<circle class="node" cx="${x0}" cy="${y}" r="5" fill="${sign>0?'#3fb950':'#d29922'}" onclick="sel(${j})"><title>${esc(D.names[j])} (${w})</title></circle>`;
      g+=`<text class="lbl" x="${x0+(sign>0?10:-10)}" y="${y+4}" text-anchor="${sign>0?'start':'end'}" onclick="sel(${j})">${esc(trunc(D.names[j]))}</text>`;
    });
  }
  spoke(O,W-150,1); spoke(I,150,-1);
  g+=`<circle cx="${cx}" cy="${cy}" r="9" fill="#58a6ff"/><text class="lbl" x="${cx}" y="${cy-14}" text-anchor="middle" style="font-size:13px;font-weight:700">${esc(trunc(D.names[i]))}</text>`;
  g+=`<text x="${W-150}" y="30" text-anchor="middle" fill="#3fb950" style="font-size:11px">引用先 →</text>`;
  g+=`<text x="150" y="30" text-anchor="middle" fill="#d29922" style="font-size:11px">← 被引用</text>`;
  svg.innerHTML=g;
}
// start: show the top hub
sel(hub[0][0]);
</script></body></html>"""
html=(HTML.replace("__DATA__",json.dumps(data,ensure_ascii=False,separators=(",",":")))
          .replace("__NLAWS__",f"{len(laws):,}").replace("__NPAIRS__",f"{len(edges):,}")
          .replace("__SNAP__", stats.get("egov_snapshot", "")))
(REL/"explorer.html").write_text(html,encoding="utf-8-sig")
print(f"wrote explorer.html ({len(html)//1024} KB)")
