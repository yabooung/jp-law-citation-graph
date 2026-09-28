"""Retrieval baseline on the NTA 質疑応答事例 gold set (no embeddings).

Each gold record is a real tax question with the article-level provisions the
NTA answer cites (`gold_articles`). We retrieve articles for the question text
and report Recall@k / MRR at the Article level.

Methods
    bm25        character-trigram OR query, BM25 over chunks (search --nl);
                chunks are mapped to their Article, first occurrence wins.
    bm25+graph  bm25, then each of the top-N chunks spreads a share of its
                reciprocal-rank score to the Articles it CITES (one hop).

Usage:
    jlawcite eval --gold data/parsed/jp_nta_gold.jsonl
    jlawcite eval --gold ... --limit 300 --out eval.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from jlawcite.search import SearchDB

_ARTICLE_OF = re.compile(r"^(.*?_a(?:sup-[^-]+-)?[0-9][0-9-]*?)(?:_p\d+.*)?$")
KS = (1, 5, 10, 20, 50)


def article_of(node_id: str) -> str | None:
    """Article id for a Paragraph / Item / Article id; None for others."""
    if "_at-" in node_id or "_h" in node_id.split("_", 1)[-1][:2]:
        return None
    m = _ARTICLE_OF.match(node_id)
    return m.group(1) if m and "_a" in node_id else None


def rank_bm25(db: SearchDB, query: str, depth: int) -> list[tuple[str, float]]:
    out: dict[str, float] = {}
    for rank, hit in enumerate(db.search(query, natural=True, limit=depth,
                                         include_inactive=True)):
        art = hit["article_id"]
        if art and art not in out:
            out[art] = 1.0 / (60 + rank)
    return sorted(out.items(), key=lambda x: -x[1])


def rank_bm25_graph(db: SearchDB, query: str, depth: int, expand_top: int = 20,
                    weight: float = 0.5) -> list[tuple[str, float]]:
    hits = db.search(query, natural=True, limit=depth, include_inactive=True)
    score: dict[str, float] = defaultdict(float)
    seen: set[str] = set()
    for rank, hit in enumerate(hits):
        rr = 1.0 / (60 + rank)
        art = hit["article_id"]
        if art and art not in seen:
            seen.add(art)
            score[art] += rr
        if rank < expand_top:
            for e in db.refs(hit["node_id"], direction="out", rels=["CITES"],
                             limit=50).get("out", []):
                tgt = article_of(e["target"])
                if tgt and tgt != art:
                    score[tgt] += weight * rr
    return sorted(score.items(), key=lambda x: -x[1])


def evaluate(db: SearchDB, gold_rows: list[dict], method, depth: int) -> dict:
    hits_at = {k: 0 for k in KS}
    rr_sum = 0.0
    n = 0
    t0 = time.time()
    for g in gold_rows:
        ranked = [a for a, _ in method(db, g["query"], depth)][:max(KS)]
        n += 1
        first = next((i for i, a in enumerate(ranked) if a in g["gold"]), None)
        if first is not None:
            rr_sum += 1.0 / (first + 1)
            for k in KS:
                if first < k:
                    hits_at[k] += 1
    return {
        "queries": n,
        **{f"recall@{k}": round(hits_at[k] / n, 4) for k in KS},
        "mrr@50": round(rr_sum / n, 4),
        "sec_per_query": round((time.time() - t0) / max(n, 1), 3),
    }


def load_gold(path: Path, db: SearchDB) -> tuple[list[dict], dict]:
    rows, stats = [], {"records": 0, "with_gold": 0, "usable": 0}
    for line in path.open(encoding="utf-8"):
        r = json.loads(line)
        stats["records"] += 1
        arts = {a for a in (article_of(x) for x in r.get("gold_articles") or []) if a}
        if not arts:
            continue
        stats["with_gold"] += 1
        present = {a for a in arts if db.node(a)}
        if present:
            stats["usable"] += 1
            rows.append({"id": r["id"], "query": r["query"], "gold": present})
    return rows, stats


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Retrieval baseline on the NTA gold set")
    ap.add_argument("--db", type=Path, default=Path("data/search/jp_search.sqlite"))
    ap.add_argument("--gold", type=Path, default=Path("data/parsed/jp_nta_gold.jsonl"))
    ap.add_argument("--limit", type=int, default=None, help="evaluate the first N usable queries")
    ap.add_argument("--depth", type=int, default=100, help="chunks retrieved per query")
    ap.add_argument("--out", type=Path, help="write results JSON here")
    a = ap.parse_args(argv)

    db = SearchDB(a.db)
    rows, stats = load_gold(a.gold, db)
    if a.limit:
        rows = rows[: a.limit]
    print(f"gold: {stats['records']} records, {stats['with_gold']} with article-level "
          f"answers, {stats['usable']} whose articles exist in this snapshot; "
          f"evaluating {len(rows)}")
    results = {"gold": stats, "evaluated": len(rows), "methods": {}}
    for name, fn in (("bm25", rank_bm25), ("bm25+graph", rank_bm25_graph)):
        res = evaluate(db, rows, fn, a.depth)
        results["methods"][name] = res
        print(f"{name:>11}: " + "  ".join(f"{k}={v}" for k, v in res.items() if k != "queries"))
    if a.out:
        a.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
