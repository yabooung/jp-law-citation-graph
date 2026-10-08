"""Block a monthly publish when the new snapshot is clearly worse than the last release.

The refresh builds, validates and benchmarks a new snapshot unattended, then publishes it. `validate`
catches broken files; it does not catch a parser change or an e-Gov format change that silently drops
citations or hurts retrieval while every step still exits 0. This compares the new snapshot with the
release committed in the repo and exits 1 if anything fell past a threshold, so the publish step is
skipped and the run goes red.

    python tools/regression_gate.py \
        --new-results work/release/nta_retrieval_results.json --base-results eval/v2/nta_retrieval_results.json \
        --new-stats work/release/data/release_stats.json      --base-stats data/release_stats.json

Thresholds are deliberately loose: laws are added and repealed every month, so counts move by
well under 1% on their own. Increases never fail.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# (label, how to read it, max allowed drop, "abs" = absolute points / "rel" = fraction of the base)
RETRIEVAL_CHECKS = [
    ("recall@10 bm25+graph", ("methods", "bm25+graph", "recall@10"), 0.02, "abs"),
    ("recall@10 bm25", ("methods", "bm25", "recall@10"), 0.02, "abs"),
    ("mrr@50 bm25+graph", ("methods", "bm25+graph", "mrr@50"), 0.02, "abs"),
    ("queries evaluated", ("evaluated",), 0.02, "rel"),
]
STATS_CHECKS = [
    ("laws", ("laws",), 0.02, "rel"),
    ("CITES edges", ("edges_by_rel", "CITES"), 0.03, "rel"),
    ("DELEGATES_TO edges", ("edges_by_rel", "DELEGATES_TO"), 0.05, "rel"),
    ("REFERS_TO_ATTACHMENT edges", ("edges_by_rel", "REFERS_TO_ATTACHMENT"), 0.05, "rel"),
    ("law-to-law pairs", ("law_to_law_pairs",), 0.03, "rel"),
    ("cross-law citations resolved", ("external_cross_law_edges",), 0.03, "rel"),
]


def _get(d: dict, path: tuple[str, ...]):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def compare(new: dict, base: dict, checks) -> list[dict]:
    rows = []
    for label, path, limit, kind in checks:
        n, b = _get(new, path), _get(base, path)
        if n is None or b is None:
            rows.append({"check": label, "base": b, "new": n, "drop": None, "limit": limit, "kind": kind,
                         "ok": False, "note": "missing"})
            continue
        drop = (b - n) if kind == "abs" else ((b - n) / b if b else 0.0)
        rows.append({"check": label, "base": b, "new": n, "drop": drop, "limit": limit, "kind": kind,
                     "ok": drop <= limit, "note": ""})
    return rows


def _fmt(v, kind):
    if v is None:
        return "—"
    if isinstance(v, float) and kind == "abs":
        return f"{v:.4f}"
    if isinstance(v, float):
        return f"{v * 100:+.2f}%" if kind == "drop%" else f"{v:.4f}"
    return f"{v:,}"


def render(rows: list[dict]) -> str:
    lines = ["| check | base | new | drop | allowed | |", "|---|---:|---:|---:|---:|---|"]
    for r in rows:
        if r["drop"] is None:
            drop = "—"
        elif r["kind"] == "abs":
            drop = f"{r['drop']:+.4f}"
        else:
            drop = f"{r['drop'] * 100:+.2f}%"
        allowed = f"{r['limit']:.2f}" if r["kind"] == "abs" else f"{r['limit'] * 100:.0f}%"
        mark = "ok" if r["ok"] else f"**FAIL** {r['note']}".strip()
        lines.append(f"| {r['check']} | {_fmt(r['base'], 'abs')} | {_fmt(r['new'], 'abs')} | {drop} | {allowed} | {mark} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--new-results", type=Path, required=True)
    ap.add_argument("--base-results", type=Path, required=True)
    ap.add_argument("--new-stats", type=Path, required=True)
    ap.add_argument("--base-stats", type=Path, required=True)
    a = ap.parse_args(argv)
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731
    rows = (compare(load(a.new_results), load(a.base_results), RETRIEVAL_CHECKS)
            + compare(load(a.new_stats), load(a.base_stats), STATS_CHECKS))
    table = render(rows)
    failed = [r["check"] for r in rows if not r["ok"]]
    verdict = "PASS" if not failed else f"FAIL — {', '.join(failed)}"
    out = f"### Regression gate: {verdict}\n\n{table}\n"
    print(out)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(out + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
