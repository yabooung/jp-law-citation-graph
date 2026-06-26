#!/usr/bin/env python3
"""JLaw-CiteGraph MCP server.

Exposes the Japanese statutory citation graph + deterministic resolver to LLMs
via the Model Context Protocol. An LLM (e.g. Claude) can resolve citation
strings to specific laws/articles and traverse the citation network for grounding.

Tools:
  resolve_citation(text)   parse a Japanese legal text → resolved law citations
  what_cites(law)          laws that cite the given law (incoming)
  what_law_cites(law)      laws cited by the given law (outgoing)
  citation_path(a, b)      shortest citation path between two laws (<=4 hops)
  get_law(query)           look up a law (id/name) + metadata + degree

Run:  pip install -r requirements.txt
      python server.py          # stdio MCP server
Data: reads ../data/laws.csv, ../data/cites_law_to_law.csv and the resolver
      (../src/jlawcite). Pure graph queries are deterministic.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jlawcite import citation, resolver  # noqa: E402

# ---- load graph ------------------------------------------------------------
_NAME, _ID = {}, {}          # law_id -> name ; name -> law_id
_TYPE, _URL = {}, {}
_OUT = defaultdict(list)     # law_id -> [(tgt_id, weight)]
_IN = defaultdict(list)      # law_id -> [(src_id, weight)]


def _load():
    with (ROOT / "data" / "laws.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            _NAME[r["law_id"]] = r["name"]; _ID[r["name"]] = r["law_id"]
            _TYPE[r["law_id"]] = r["type"]; _URL[r["law_id"]] = r["url"]
    with (ROOT / "data" / "cites_law_to_law.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            s, t, w = r["src_law_id"], r["tgt_law_id"], int(r["n_citations"])
            _OUT[s].append((t, w)); _IN[t].append((s, w))
    for d in (_OUT, _IN):
        for k in d:
            d[k].sort(key=lambda x: -x[1])
    # resolver index from the public law list (canonical + alias; deterministic)
    aliases = resolver.load_aliases(ROOT / "src" / "jlawcite" / "jp_law_aliases.json")
    return resolver.LawNameIndex(canonical_to_id=_ID, promulgation_to_id={},
                                 alias_to_canonical=aliases, old_to_id={})


_IDX = _load()


def _resolve_name(query: str) -> str | None:
    """Accept a law_id or (exact/abbrev) name, return law_id."""
    if query in _NAME:
        return query
    if query in _ID:
        return _ID[query]
    hit = _IDX.resolve(query, None)
    return hit.law_id if hit else None


# ---- tool implementations (plain functions; MCP wraps these) ---------------
def resolve_citation(text: str) -> list[dict]:
    """Resolve external law citations found in `text` to specific laws/articles."""
    out = []
    for er in citation.extract_external(text)[0]:
        name, _ = _IDX.trim_overgrab(er.law_name_raw)
        hit = _IDX.resolve(name, er.promulgation)
        out.append({"cited_text": er.raw, "law": (_NAME.get(hit.law_id) if hit else None),
                    "law_id": (hit.law_id if hit else None),
                    "article": er.article_num, "via": (hit.via if hit else None),
                    "resolved": hit is not None})
    return out


def what_cites(law: str, limit: int = 30) -> dict:
    lid = _resolve_name(law)
    if not lid:
        return {"error": f"law not found: {law}"}
    items = [{"law": _NAME.get(s, s), "law_id": s, "weight": w} for s, w in _IN[lid][:limit]]
    return {"law": _NAME.get(lid), "law_id": lid, "cited_by_count": len(_IN[lid]), "cited_by": items}


def what_law_cites(law: str, limit: int = 30) -> dict:
    lid = _resolve_name(law)
    if not lid:
        return {"error": f"law not found: {law}"}
    items = [{"law": _NAME.get(t, t), "law_id": t, "weight": w} for t, w in _OUT[lid][:limit]]
    return {"law": _NAME.get(lid), "law_id": lid, "cites_count": len(_OUT[lid]), "cites": items}


def citation_path(a: str, b: str, max_hops: int = 4) -> dict:
    sa, sb = _resolve_name(a), _resolve_name(b)
    if not sa or not sb:
        return {"error": "law not found"}
    # BFS over outgoing edges
    prev = {sa: None}
    q = deque([(sa, 0)])
    while q:
        cur, d = q.popleft()
        if cur == sb:
            path = []
            while cur is not None:
                path.append(_NAME.get(cur, cur)); cur = prev[cur]
            return {"from": _NAME.get(sa), "to": _NAME.get(sb), "hops": len(path) - 1,
                    "path": list(reversed(path))}
        if d >= max_hops:
            continue
        for t, _w in _OUT[cur]:
            if t not in prev:
                prev[t] = cur; q.append((t, d + 1))
    return {"from": _NAME.get(sa), "to": _NAME.get(sb), "path": None,
            "note": f"no citation path within {max_hops} hops"}


def get_law(query: str) -> dict:
    lid = _resolve_name(query)
    if not lid:
        return {"error": f"law not found: {query}"}
    return {"law_id": lid, "name": _NAME.get(lid), "type": _TYPE.get(lid),
            "url": _URL.get(lid), "cites_count": len(_OUT[lid]), "cited_by_count": len(_IN[lid])}


# ---- MCP wiring ------------------------------------------------------------
def build_server():
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("jlaw-citegraph")
    mcp.tool()(resolve_citation)
    mcp.tool()(what_cites)
    mcp.tool()(what_law_cites)
    mcp.tool()(citation_path)
    mcp.tool()(get_law)
    return mcp


if __name__ == "__main__":
    build_server().run()  # stdio transport
