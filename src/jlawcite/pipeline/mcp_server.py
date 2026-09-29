"""MCP server: the Japanese statutory citation graph + deterministic resolver for LLMs.

    pip install "jlawcite[mcp]"
    <prog> mcp                                 stdio MCP server
    claude mcp add jlawcite -- uvx --from "jlawcite[mcp]" jlawcite mcp     (no install)

On first start, if no data is found, it downloads the latest snapshot in the background
(same as `download`); graph tools are ready in seconds, text/search tools after ~2 minutes.

Tools:
  resolve_citation(text)   parse Japanese legal text → resolved law citations
  what_cites(law)          laws that cite the given law (incoming)
  what_law_cites(law)      laws cited by the given law (outgoing)
  citation_path(a, b)      shortest citation path between two laws (<=4 hops)
  get_law(query)           law metadata + in/out degree + e-Gov link
  pending_amendments(law)  upcoming amendments (施行日, amending law)
  get_provision(citation)  「民法第七百九条」 → text + what it cites / what cites it
  search_statutes(query)   BM25 keyword / natural-language search

Data: laws.csv, cites_law_to_law.csv, pending_versions.csv from $JLAWCITE_DATA, else ./data,
else the download cache; the search DB from $JLAWCITE_DB, else ./data/search, else the cache.
"""
from __future__ import annotations

import csv
import functools
import os
import sys
import threading
from collections import defaultdict, deque
from pathlib import Path

from jlawcite.citation import extract_external
from jlawcite.resolver import LawNameIndex, load_aliases
from jlawcite.search import SearchDB
from jlawcite.pipeline import download
from jlawcite.pipeline.ingest_full import _DEFAULT_ALIAS_PATH
from jlawcite.pipeline.search_cli import CACHE_DB, default_db

_LAW_CSV = "laws.csv"


def data_dir() -> Path:
    if os.environ.get("JLAWCITE_DATA"):
        return Path(os.environ["JLAWCITE_DATA"])
    if (Path("data") / _LAW_CSV).exists():
        return Path("data")
    return CACHE_DB.parent


class _Graph:
    """Law-level graph and resolver, loaded once from the CSV files."""

    def __init__(self, d: Path):
        self.name, self.id, self.type, self.url = {}, {}, {}, {}
        self.out, self.inc = defaultdict(list), defaultdict(list)
        self.pending = defaultdict(list)
        with (d / "laws.csv").open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                lid = r["law_id"]
                self.name[lid], self.type[lid], self.url[lid] = r["name"], r["type"], r["url"]
                self.id[r["name"]] = lid
        with (d / "cites_law_to_law.csv").open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                s, t, w = r["src_law_id"], r["tgt_law_id"], int(r["n_citations"])
                self.out[s].append((t, w))
                self.inc[t].append((s, w))
        for adj in (self.out, self.inc):
            for k in adj:
                adj[k].sort(key=lambda x: -x[1])
        pend = d / "pending_versions.csv"
        if pend.exists():
            with pend.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self.pending[r["law_id"]].append(r)
        self.idx = LawNameIndex(
            canonical_to_id=self.id, promulgation_to_id={},
            alias_to_canonical=load_aliases(_DEFAULT_ALIAS_PATH), old_to_id={})

    def resolve_name(self, query: str) -> str | None:
        """Accept a law_id or (exact/abbrev) name, return law_id."""
        if query in self.name:
            return query
        if query in self.id:
            return self.id[query]
        hit = self.idx.resolve(query, None)
        return hit.law_id if hit else None


# ---- state: data may still be downloading on first run -----------------------
_lock = threading.Lock()
_graph: _Graph | None = None
_download_error: str | None = None
_downloading = threading.Event()
_BUSY = ("JLaw-CiteGraph data is still downloading (first run, about 2 minutes). "
         "Try again shortly.")


def _g() -> _Graph:
    global _graph
    with _lock:
        if _graph is None:
            d = data_dir()
            need = download.LAW_FILES if _downloading.is_set() else download.LAW_FILES[:2]
            if not all((d / f).exists() for f in need):
                raise RuntimeError(_download_error or _BUSY)
            _graph = _Graph(d)
        return _graph


def _db() -> SearchDB:
    if _downloading.is_set():
        raise RuntimeError(_BUSY)
    db = default_db()
    if not db.exists():
        raise RuntimeError(_download_error or f"search index not found at {db} — run `jlawcite download`")
    return SearchDB(db)


def _background_download() -> None:
    global _download_error
    _downloading.set()
    try:
        download.download_db("main", CACHE_DB)
    except Exception as e:  # noqa: BLE001 — reported through the tools
        _download_error = f"download failed: {e} — run `jlawcite download` manually"
    finally:
        _downloading.clear()


def ensure_data() -> bool:
    """Start a background download when neither the law files nor a DB are present."""
    if (data_dir() / _LAW_CSV).exists() or default_db().exists():
        return False
    threading.Thread(target=_background_download, daemon=True).start()
    return True


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001 — surfaced to the LLM as a message
            return {"error": str(e)}
    return wrapper


# ---- tools (plain functions; MCP wraps these) --------------------------------
def resolve_citation(text: str) -> list[dict] | dict:
    """Resolve external law citations found in `text` to specific laws/articles."""
    g = _g()
    out = []
    for er in extract_external(text)[0]:
        name, _ = g.idx.trim_overgrab(er.law_name_raw)
        hit = g.idx.resolve(name, er.promulgation)
        out.append({"cited_text": er.raw, "law": (g.name.get(hit.law_id) if hit else None),
                    "law_id": (hit.law_id if hit else None),
                    "article": er.article_path, "paragraph": er.paragraph,
                    "item": er.item_path, "suppl": er.suppl,
                    "via": (hit.via if hit else None), "resolved": hit is not None})
    return out


def what_cites(law: str, limit: int = 30) -> dict:
    """Laws that cite the given law (incoming), heaviest first."""
    g = _g()
    lid = g.resolve_name(law)
    if not lid:
        return {"error": f"law not found: {law}"}
    items = [{"law": g.name.get(s, s), "law_id": s, "weight": w} for s, w in g.inc[lid][:limit]]
    return {"law": g.name.get(lid), "law_id": lid, "cited_by_count": len(g.inc[lid]), "cited_by": items}


def what_law_cites(law: str, limit: int = 30) -> dict:
    """Laws cited by the given law (outgoing), heaviest first."""
    g = _g()
    lid = g.resolve_name(law)
    if not lid:
        return {"error": f"law not found: {law}"}
    items = [{"law": g.name.get(t, t), "law_id": t, "weight": w} for t, w in g.out[lid][:limit]]
    return {"law": g.name.get(lid), "law_id": lid, "cites_count": len(g.out[lid]), "cites": items}


def citation_path(a: str, b: str, max_hops: int = 4) -> dict:
    """Shortest citation path from law `a` to law `b` (outgoing edges, up to max_hops)."""
    g = _g()
    sa, sb = g.resolve_name(a), g.resolve_name(b)
    if not sa or not sb:
        return {"error": "law not found"}
    prev = {sa: None}
    q = deque([(sa, 0)])
    while q:
        cur, d = q.popleft()
        if cur == sb:
            path = []
            while cur is not None:
                path.append(g.name.get(cur, cur))
                cur = prev[cur]
            return {"from": g.name.get(sa), "to": g.name.get(sb), "hops": len(path) - 1,
                    "path": list(reversed(path))}
        if d >= max_hops:
            continue
        for t, _w in g.out[cur]:
            if t not in prev:
                prev[t] = cur
                q.append((t, d + 1))
    return {"from": g.name.get(sa), "to": g.name.get(sb), "path": None,
            "note": f"no citation path within {max_hops} hops"}


def get_law(query: str) -> dict:
    """Look up a law by id or name: metadata, e-Gov link, in/out citation degree."""
    g = _g()
    lid = g.resolve_name(query)
    if not lid:
        return {"error": f"law not found: {query}"}
    return {"law_id": lid, "name": g.name.get(lid), "type": g.type.get(lid),
            "url": g.url.get(lid), "cites_count": len(g.out[lid]), "cited_by_count": len(g.inc[lid])}


def pending_amendments(law: str) -> dict:
    """Upcoming amendments of a law: 施行日, amending law, 施行日備考 (e-Gov 未施行 versions)."""
    g = _g()
    lid = g.resolve_name(law)
    if not lid:
        return {"error": f"law not found: {law}"}
    return {"law": g.name.get(lid), "law_id": lid, "pending": g.pending.get(lid, [])}


def get_provision(citation_text: str) -> dict:
    """Text of a provision from a citation string (「民法第七百九条」, 「所得税法施行令14条2項」,
    official abbreviations) or node id, with the laws/articles it cites and that cite it."""
    db = _db()
    res = db.lookup(citation_text)
    refs = db.refs(res["node"]["id"], rels=["CITES"], limit=40)

    def brief(e, side):
        return {"node": e[side], "title": e.get(f"{side}_title"),
                "law": e.get(f"{side}_law_title"), "raw": e.get("raw")}
    return {"law": res["law"]["title"], "node": res["node"]["id"], "text": res["text"],
            "cites": [brief(e, "target") for e in refs.get("out", [])],
            "cited_by": [brief(e, "source") for e in refs.get("in", [])],
            "pending": res["pending"]}


def search_statutes(query: str, law: str | None = None, natural: bool = False,
                    limit: int = 10) -> dict:
    """BM25 search over provisions. Space-separated keywords are ANDed; set
    natural=True for a sentence-style question (character-trigram OR query)."""
    hits = _db().search(query, law=law, natural=natural, limit=limit)
    return {"hits": [{k: h[k] for k in ("node_id", "heading", "snippet")} for h in hits]}


TOOLS = [resolve_citation, what_cites, what_law_cites, citation_path, get_law,
         pending_amendments, get_provision, search_statutes]


def build_server():
    try:
        from mcp.server.mcpserver import MCPServer as Server   # mcp >= 2
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server       # mcp 1.x
    server = Server("jlaw-citegraph")
    for fn in TOOLS:
        server.tool()(_safe(fn))
    return server


def main(argv: list[str] | None = None) -> int:
    try:
        server = build_server()
    except ImportError as e:
        print(f'{e}\nthe MCP server needs the extra: pip install "jlawcite[mcp]"', file=sys.stderr)
        return 1
    if ensure_data():
        print("[mcp] no data found; downloading the latest snapshot in the background",
              file=sys.stderr)
    server.run()  # stdio transport
    return 0


if __name__ == "__main__":
    sys.exit(main())
