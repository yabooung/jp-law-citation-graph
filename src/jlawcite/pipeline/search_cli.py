"""jlawcite — embedding-free search CLI over the parsed graph.

    jlawcite index                      # data/parsed → data/search/jp_search.sqlite
    jlawcite search 解雇 予告            # BM25 keyword search (terms ANDed)
    jlawcite get 民法第七百九条          # citation string → provision text
    jlawcite get 所得税法施行令14条2項
    jlawcite refs 労働基準法第二十条     # cites / cited-by / delegation / attachments
    jlawcite law 労働基準法 --toc        # law info, structure, pending amendments
    jlawcite pending --until 20261231   # upcoming amendments
    jlawcite stats

Every command accepts --json (JSON Lines on stdout) for research pipelines.
See docs/SEARCH.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from jlawcite.search import CitationLookupError, SearchDB, build_index

LOCAL_DB = Path("data/search/jp_search.sqlite")
CACHE_DB = Path(os.environ.get("JLAWCITE_HOME") or Path.home() / ".cache" / "jlawcite") / "jp_search.sqlite"


def default_db() -> Path:
    """$JLAWCITE_DB, else a local build, else a `download`ed DB, else the local build path."""
    if os.environ.get("JLAWCITE_DB"):
        return Path(os.environ["JLAWCITE_DB"])
    if not LOCAL_DB.exists() and CACHE_DB.exists():
        return CACHE_DB
    return LOCAL_DB


DEFAULT_DB = default_db()


def _emit_json(obj) -> None:
    if isinstance(obj, list):
        for o in obj:
            print(json.dumps(o, ensure_ascii=False))
    else:
        print(json.dumps(obj, ensure_ascii=False))


def _fmt_date(d: str | None) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if d and len(d) == 8 else (d or "-")


def _law_line(law: dict) -> str:
    status = "施行中" if law["is_active"] else "未施行"
    nxt = f", 次回改正 {_fmt_date(law['next_enforcement_date'])}" if law["next_enforcement_date"] else ""
    return (f"{law['title']}  [{law['law_id']}, {law['law_type']}, "
            f"{law.get('promulgation_no') or ''}]  現行 {_fmt_date(law['enforcement_date'])} {status}{nxt}")


def _print_pending(rows: list[dict], indent: str = "") -> None:
    for p in rows:
        note = f" ({p['enforcement_note']})" if p.get("enforcement_note") else ""
        print(f"{indent}{_fmt_date(p['enforcement_date'])}  {p.get('law_title') or p['law_id']}"
              f" ← {p.get('amend_law_name') or ''} {p.get('amend_law_num') or ''}{note}")


# ---------------------------------------------------------------------------
def cmd_build(a) -> int:
    meta = build_index(a.data, a.db, csv_path=a.csv, aliases_path=a.aliases)
    if a.json:
        _emit_json(meta)
    return 0


def cmd_search(a) -> int:
    rows = SearchDB(a.db).search(
        " ".join(a.query), law=a.law, law_type=a.type, section=a.section,
        include_inactive=a.include_inactive, limit=a.limit, offset=a.offset, natural=a.nl)
    if a.json:
        _emit_json([{k: r[k] for k in ("node_id", "law_id", "article_id", "section",
                                         "heading", "score", "snippet")}
                    | ({"body": r["body"]} if a.full else {}) for r in rows])
        return 0
    if not rows:
        print("(no results)")
        return 1
    for i, r in enumerate(rows, 1 + a.offset):
        print(f"{i:>3}. {r['heading']}   [{r['node_id']}]")
        print(f"     {r['body'] if a.full else r['snippet'].replace(chr(10), ' ')}")
    return 0


def cmd_get(a) -> int:
    db = SearchDB(a.db)
    res = db.lookup(" ".join(a.ref), law_hint=a.law)
    if a.json:
        _emit_json(res)
        return 0
    n, law = res["node"], res["law"]
    print(_law_line(law))
    if res.get("note"):
        print(f"※ {res['note']}")
    print(f"[{n['id']}] {n['type']}")
    print()
    if n["type"] == "Law":
        print("(法令全体 — `law --toc` で構成、`search --law` で本文検索)")
    else:
        print(res["text"])
    if res["pending"]:
        print("\n改正予定:")
        _print_pending(res["pending"], "  ")
    return 0


def cmd_refs(a) -> int:
    db = SearchDB(a.db)
    ref = " ".join(a.ref)
    node = db.node(ref) or db.lookup(ref, law_hint=a.law)["node"]
    res = db.refs(node["id"], direction=a.direction, rels=a.rel, limit=a.limit)
    if a.json:
        _emit_json({"node": node["id"], **res})
        return 0
    print(f"{node['title']}  [{node['id']}]")
    for key, label, other, other_title, other_law in (
            ("out", "→ 引用・参照先", "target", "target_title", "target_law_title"),
            ("in", "← 被引用", "source", "source_title", "source_law_title")):
        if key not in res:
            continue
        rows = res[key]
        print(f"\n{label} ({len(rows)}{'+' if len(rows) >= a.limit else ''})")
        for e in rows:
            tag = e["rel"] if e["rel"] != "CITES" else (e.get("extracted_from") or "CITES")
            print(f"  {e[other_law] or ''} {e[other_title] or ''}  [{e[other]}]"
                  f"  「{(e.get('raw') or '')[-30:]}」 {tag}")
    return 0


def cmd_law(a) -> int:
    db = SearchDB(a.db)
    law = db.resolve_law(" ".join(a.name))
    pend = db.pending(law["law_id"])
    toc = db.toc(law["law_id"]) if a.toc else []
    if a.json:
        _emit_json({"law": law, "pending": pend, "toc": toc})
        return 0
    print(_law_line(law))
    if pend:
        print("\n改正予定:")
        _print_pending(pend, "  ")
    if a.toc:
        print()
        depth = {law["law_id"]: -1}
        for t in toc:
            d = depth.get(t["parent_id"], -1) + 1
            depth[t["id"]] = d
            print(f"{'  ' * d}{t['title']}  [{t['id']}]")
    return 0


def cmd_pending(a) -> int:
    db = SearchDB(a.db)
    law_id = db.resolve_law(a.law)["law_id"] if a.law else None
    rows = db.pending(law_id, until=a.until, limit=a.limit)
    if a.json:
        _emit_json(rows)
        return 0
    _print_pending(rows)
    return 0


def cmd_stats(a) -> int:
    s = SearchDB(a.db).stats()
    if a.json:
        _emit_json(s)
        return 0
    for k, v in s.items():
        print(f"{k:>18}: {v}")
    return 0


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    ap = argparse.ArgumentParser(prog="jlawcite",
                                 description="Search the Japanese statute graph (no embeddings).")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"search DB (default: {DEFAULT_DB})")
    ap.add_argument("--json", action="store_true", help="JSON Lines output")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the search DB from ingest outputs")
    b.add_argument("--data", type=Path, default=Path("data/parsed"))
    b.add_argument("--csv", type=Path, default=Path("data/raw/law_xml/all_law_list.csv"),
                   help="e-Gov all_law_list.csv (adds 旧法令名 lookups; optional)")
    b.add_argument("--aliases", type=Path, default=Path(__file__).resolve().parent.parent / "jp_law_aliases.json")
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser("search", help="keyword search (BM25, trigram)")
    s.add_argument("query", nargs="+")
    s.add_argument("--law", help="restrict to one law (name / law_id / 公布番号)")
    s.add_argument("--type", choices=["act", "cabinet_order", "ministerial", "imperial_order",
                                      "dajokan", "other"])
    s.add_argument("--section", choices=["all", "main", "suppl"], default="all")
    s.add_argument("--include-inactive", action="store_true", help="include laws not yet in force")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--full", action="store_true", help="print full chunk text")
    s.add_argument("--nl", action="store_true",
                   help="natural-language query: OR of character trigrams, BM25-ranked")
    s.set_defaults(fn=cmd_search)

    g = sub.add_parser("get", help="citation string or node id → text")
    g.add_argument("ref", nargs="+", help="e.g. 民法第七百九条, 所得税法施行令14条2項, node id")
    g.add_argument("--law", help="law for a bare 第N条")
    g.set_defaults(fn=cmd_get)

    r = sub.add_parser("refs", help="citation graph around a node")
    r.add_argument("ref", nargs="+")
    r.add_argument("--law")
    r.add_argument("--direction", choices=["in", "out", "both"], default="both")
    r.add_argument("--rel", action="append",
                   choices=["CITES", "DELEGATES_TO", "REFERS_TO_ATTACHMENT", "AMENDS"])
    r.add_argument("--limit", type=int, default=100)
    r.set_defaults(fn=cmd_refs)

    lw = sub.add_parser("law", help="law info, pending amendments, --toc structure")
    lw.add_argument("name", nargs="+")
    lw.add_argument("--toc", action="store_true")
    lw.set_defaults(fn=cmd_law)

    p = sub.add_parser("pending", help="upcoming amendments")
    p.add_argument("--law")
    p.add_argument("--until", help="YYYYMMDD")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(fn=cmd_pending)

    st = sub.add_parser("stats", help="DB summary")
    st.set_defaults(fn=cmd_stats)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (CitationLookupError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
