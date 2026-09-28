"""Export release data files (JLaw-CiteGraph layout) from ingest outputs.

Writes, into --out:
    laws.csv                law_id, name, type, url (+ enforcement_date,
                            next_enforcement_date, pending_versions)
    cites_edges.jsonl.gz    every resolved *external* citation (another law, or
                            the law's own amended/defined version — 新法/旧法 style),
                            article-level, with via / confidence (v1 fields) plus
                            node ids and extracted_from
    cites_law_to_law.csv    aggregated src_law → tgt_law counts (self-loops excluded)
    cites_all_edges.jsonl.gz  every edge in the graph: CITES (incl. same-law and
                            前条/同項 references), DELEGATES_TO, REFERS_TO_ATTACHMENT,
                            AMENDS — compact fields
    pending_versions.csv    upcoming amendments per law
    release_stats.json      counts used in the README / data card

The first three files keep the v1 column names, so v1 consumers keep working.

Usage:
    jlawcite export --parsed data/parsed \\
        --csv data/raw/law_xml/all_law_list.csv --out release/data
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# extracted_from prefixes that denote a citation of a law named in the text
_EXTERNAL = ("EXTERNAL_FULL_PAT/", "NAKED_LAW_PAT/", "INTERNAL_PAT/enum_carryover")


def _jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _via(extracted_from: str) -> str:
    if extracted_from == "INTERNAL_PAT/enum_carryover":
        return "enum_carryover"
    return extracted_from.split("/", 1)[1] if "/" in extracted_from else extracted_from


def _law_types(csv_path: Path | None) -> dict[tuple[str, str], str]:
    """(law_id, mst_id) → 法令種別 from e-Gov all_law_list.csv."""
    out: dict[tuple[str, str], str] = {}
    if not csv_path or not csv_path.exists():
        return out
    with csv_path.open(encoding="utf-8-sig") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if len(row) > 12:
                out[(row[11], row[12].rstrip("/").rsplit("/", 1)[-1])] = row[0]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export JLaw-CiteGraph release data files")
    ap.add_argument("--parsed", type=Path, default=Path("data/parsed"))
    ap.add_argument("--csv", type=Path, default=Path("data/raw/law_xml/all_law_list.csv"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--snapshot", type=Path, default=Path("data/raw/law_xml/_snapshot.json"),
                    help="fetch_egov snapshot metadata (for the snapshot date)")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)

    # ---- nodes: laws + a node → (law_id, article label, section) map ----
    types = _law_types(a.csv)
    laws: dict[str, dict] = {}
    where: dict[str, tuple[str, str]] = {}   # node id → (article label, section)
    for n in _jsonl(a.parsed / "jp_nodes.jsonl"):
        t = n["type"]
        if t == "Law":
            laws[n["id"]] = n
        elif t != "Hierarchy":
            label = n.get("article_path") or ""
            if t == "Attachment":
                label = n["id"].split("_at-", 1)[1]
            where[n["id"]] = (label, n.get("section") or "main")

    pending = defaultdict(list)
    pending_rows = list(_jsonl(a.parsed / "jp_pending_versions.jsonl"))
    for p in pending_rows:
        pending[p["law_id"]].append(p)

    with (a.out / "laws.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["law_id", "name", "type", "url", "enforcement_date",
                    "next_enforcement_date", "pending_versions"])
        for lid in sorted(laws):
            n = laws[lid]
            mst = n.get("mst_id") or ""
            w.writerow([lid, n["title"], types.get((lid, mst), ""),
                        f"https://laws.e-gov.go.jp/law/{lid}/{mst}" if mst else "",
                        n.get("enforcement_date") or "", n.get("next_enforcement_date") or "",
                        len(pending.get(lid, []))])

    # ---- edges ----
    law_of = lambda node_id: node_id.split("_", 1)[0]
    pair = Counter()
    n_ext = n_ext_cross = 0
    via_count = Counter()
    rel_count = Counter()
    with gzip.open(a.out / "cites_edges.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as fe, \
         gzip.open(a.out / "cites_all_edges.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as fa:
        for fname in ("jp_cites_edges.jsonl", "jp_delegates_edges.jsonl",
                      "jp_attaches_edges.jsonl", "jp_amends_edges.jsonl"):
            fp = a.parsed / fname
            if not fp.exists():
                continue
            for e in _jsonl(fp):
                rel_count[e["rel"]] += 1
                fa.write(json.dumps({k: e[k] for k in (
                    "source", "target", "rel", "raw", "extracted_from",
                    "fallback_level", "confidence", "version") if k in e}, ensure_ascii=False) + "\n")
                xf = e.get("extracted_from") or ""
                if e["rel"] != "CITES" or not xf.startswith(_EXTERNAL):
                    continue
                s_law, t_law = law_of(e["source"]), law_of(e["target"])
                s_art, s_sec = where.get(e["source"], ("", "main"))
                t_art, _ = where.get(e["target"], ("", "main"))
                via = _via(xf)
                via_count[via] += 1
                n_ext += 1
                if s_law != t_law:
                    n_ext_cross += 1
                    pair[(s_law, t_law)] += 1
                fe.write(json.dumps({
                    "src_law_id": s_law, "src_law": laws[s_law]["title"] if s_law in laws else "",
                    "src_article": s_art, "src_section": s_sec,
                    "tgt_law_id": t_law, "tgt_law": laws[t_law]["title"] if t_law in laws else "",
                    "tgt_article": t_art,
                    "via": via, "confidence": e.get("confidence", 1.0),
                    "src_node": e["source"], "tgt_node": e["target"],
                    "fallback_level": e.get("fallback_level"),
                    **({"version": e["version"]} if "version" in e else {}),
                }, ensure_ascii=False) + "\n")

    with (a.out / "cites_law_to_law.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src_law_id", "src_law", "tgt_law_id", "tgt_law", "n_citations"])
        for (s, t), c in sorted(pair.items(), key=lambda x: (-x[1], x[0])):
            w.writerow([s, laws[s]["title"], t, laws[t]["title"], c])

    with (a.out / "pending_versions.csv").open("w", encoding="utf-8", newline="") as f:
        cols = ["law_id", "law_title", "enforcement_date", "enforcement_note",
                "amend_law_name", "amend_law_num", "amend_promulgation_date", "mst_id", "url"]
        w = csv.writer(f)
        w.writerow(cols)
        for p in sorted(pending_rows, key=lambda p: (p["enforcement_date"], p["law_id"])):
            w.writerow([p.get(c) or "" for c in cols])

    cited_by = Counter(t for (_, t) in pair)
    parse_stats = json.loads((a.parsed / "jp_parse_stats.json").read_text(encoding="utf-8"))
    snap = json.loads(a.snapshot.read_text(encoding="utf-8")) if a.snapshot.exists() else {}
    stats = {
        "egov_snapshot": (snap.get("zip_csv_timestamp") or "")[:10],
        "as_of": parse_stats.get("as_of"),
        "laws": len(laws),
        "external_edges": n_ext,
        "external_cross_law_edges": n_ext_cross,
        "external_self_edges": n_ext - n_ext_cross,
        "law_to_law_pairs": len(pair),
        "edges_by_rel": dict(rel_count),
        "external_by_via": dict(via_count.most_common()),
        "pending_versions": len(pending_rows),
        "top_cited_laws": [(laws[t]["title"], c) for t, c in cited_by.most_common(10)],
    }
    (a.out / "release_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
