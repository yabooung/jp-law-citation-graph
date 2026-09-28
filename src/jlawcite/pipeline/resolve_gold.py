"""NTA shitsugi → gold dataset.

Usage:
    python -m jlawcite.pipeline.resolve_gold \
        --shitsugi data/raw/nta/shitsugi \
        --csv data/raw/law_xml/all_law_list.csv \
        --nodes data/parsed/jp_nodes.jsonl \
        --output data/parsed/jp_nta_gold.jsonl

Output format: one JSON object per case (query, answer, gold_articles, …).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tqdm import tqdm

from jlawcite.nta_processor import (
    DEFAULT_ALIAS,
    build_law_name_index,
    build_node_index,
    iter_shitsugi_files,
    process_shitsugi_case,
)


def main():
    ap = argparse.ArgumentParser(description="NTA shitsugi → gold")
    ap.add_argument("--shitsugi", required=True, type=Path,
                    help="NTA shitsugi base dir (data/raw/nta/shitsugi)")
    ap.add_argument("--csv", required=True, type=Path,
                    help="all_law_list.csv (e-Gov)")
    ap.add_argument("--nodes", required=True, type=Path,
                    help="Parsed nodes JSONL (data/parsed/jp_nodes.jsonl)")
    ap.add_argument("--output", required=True, type=Path,
                    help="Output gold JSONL")
    args = ap.parse_args()

    print("[resolve_gold] Building law_name index...", file=sys.stderr)
    law_index = build_law_name_index(args.csv)
    print(f"  {len(law_index):,} laws indexed", file=sys.stderr)

    print("[resolve_gold] Building node index...", file=sys.stderr)
    node_index = build_node_index(args.nodes)
    print(f"  {len(node_index):,} (law_id, art_path_p_num) keys indexed", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out_f = args.output.open("w", encoding="utf-8")

    n_total = 0
    n_with_gold = 0
    n_external_only = 0
    n_unresolved_only = 0

    for fp in tqdm(list(iter_shitsugi_files(args.shitsugi)), desc="Cases"):
        try:
            case = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            tqdm.write(f"[skip] {fp.name}: {e}")
            continue

        gold_entry = process_shitsugi_case(case, law_index, node_index, DEFAULT_ALIAS)
        out_f.write(json.dumps(gold_entry, ensure_ascii=False) + "\n")
        n_total += 1
        if gold_entry["gold_articles"]:
            n_with_gold += 1
        elif gold_entry["external_refs"] and not gold_entry["unresolved"]:
            n_external_only += 1
        elif gold_entry["unresolved"] and not gold_entry["gold_articles"]:
            n_unresolved_only += 1

    out_f.close()
    print(f"[resolve_gold] Total: {n_total:,}", file=sys.stderr)
    print(f"  with gold:        {n_with_gold:,} ({100 * n_with_gold / n_total:.1f}%)", file=sys.stderr)
    print(f"  external-only:    {n_external_only:,} ({100 * n_external_only / n_total:.1f}%)", file=sys.stderr)
    print(f"  unresolved-only:  {n_unresolved_only:,} ({100 * n_unresolved_only / n_total:.1f}%)", file=sys.stderr)
    print(f"  Output: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
