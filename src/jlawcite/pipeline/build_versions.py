"""Build SUPERSEDES edges across law versions.

See `docs/GRAPH_SCHEMA_V2.md` §3.1.

This script walks the e-Gov XML dump (one directory per version / 施行日 of
each law, joined to `all_law_list.csv` for labels) and emits version chain edges:

    Law(law_id @ mst_v2)  ──SUPERSEDES──▶  Law(law_id @ mst_v1)

Note: ingest keeps only the version in force at `--as-of` per law_id, so most
SUPERSEDES endpoints are *not* in `jp_nodes.jsonl`; future versions are
described in `jp_pending_versions.jsonl`. Full multi-version node ingest is
TBD (design doc §9).

Usage:
    jlawcite versions \\
        --input data/raw/law_xml \\
        --csv data/raw/law_xml/all_law_list.csv \\
        --output data/parsed/jp_versions_edges.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jlawcite.parser import list_law_versions


def main():
    ap = argparse.ArgumentParser(description="Build SUPERSEDES version chain")
    ap.add_argument("--input", type=Path, default=Path("data/raw/law_xml"),
                    help="e-Gov XML base directory (default: data/raw/law_xml)")
    ap.add_argument("--csv", type=Path, default=None,
                    help="all_law_list.csv (e-Gov, optional — adds amending-law labels)")
    ap.add_argument("--output", required=True, type=Path,
                    help="Output JSONL path")
    args = ap.parse_args()

    # Versions come from directory names (施行日 as YYYYMMDD); the CSV 施行日
    # column is 和暦 and does not sort.
    by_law = list_law_versions(args.input, args.csv)

    edges: list[dict] = []
    for law_id, versions in by_law.items():
        # Sorted oldest → newest
        for prev, curr in zip(versions, versions[1:]):
            # Encode versioned IDs by concatenation. Only one version per law
            # is in jp_nodes.jsonl (in force at ingest --as-of); the rest are
            # listed in jp_pending_versions.jsonl.
            edges.append({
                "source": f"{law_id}@{curr.mst_id}",
                "target": f"{law_id}@{prev.mst_id}",
                "rel": "SUPERSEDES",
                "raw": f"{law_id}: {prev.enforcement_date} → {curr.enforcement_date}",
                "amend_law_num": curr.amend_law_num or None,
            })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for e in edges:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"[build_versions] {len(edges):,} SUPERSEDES edges across "
          f"{sum(1 for v in by_law.values() if len(v) >= 2):,} multi-version laws",
          file=sys.stderr)


if __name__ == "__main__":
    main()
