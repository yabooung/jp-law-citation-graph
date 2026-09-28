"""Validation suite for JLaw-CiteGraph graph data (v2.0).

See `docs/GRAPH_SCHEMA_V2.md` §6 for the authoritative check list (V01–V10).

Usage:
    jlawcite validate --data data/parsed
    # or with KPI gating:
    jlawcite validate --data data/parsed --kpi

Exit codes:
    0 — all FAIL-severity checks passed
    1 — at least one FAIL-severity check failed
    2 — input files missing
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from jlawcite.ids.normalize import (
    ARTICLE_KEY_RE,
    LAW_ID_RE,
    validate_article_key,
    validate_law_id,
)


# Quality KPI thresholds (see design doc §5).
_KPI = {
    "internal_resolution_min": 0.90,
    "external_resolution_min": 0.60,
    "referential_resolution_min": 0.85,
    "fallback_paragraph_to_article_max": 0.10,
    "dangling_max": 0.0,
    "section_conflict_max": 0,
    "delegates_min": 10000,        # absolute count
    "attachments_per_law_min": 0.5,  # ratio
}

# Body-text length floors per body-bearing node type (V11).
# A parser bug of this kind (only article headers stored, ~99% empty body)
# can go unnoticed for months without a guard. Floors here
# detect a structural regression in `_direct_paragraph_text`/`_item_text`
# within one re-ingest cycle. Tuned with a 3× margin over current observed
# rates so legitimate fluctuation does not trip the gate.
_TEXT_FLOORS = {
    "Paragraph":      {"empty_pct_max": 1.0,  "len_p50_min": 30},
    "Item":           {"empty_pct_max": 1.0,  "len_p50_min": 15},
    "SupplParagraph": {"empty_pct_max": 1.5,  "len_p50_min": 30},
}


@dataclass
class CheckResult:
    id: str
    description: str
    severity: str  # FAIL | WARN
    passed: bool
    details: str = ""


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def _id_is_valid(node_id: str) -> bool:
    """Either a Law id (LAW_ID_RE) or an article_key (ARTICLE_KEY_RE)."""
    try:
        validate_article_key(node_id)
        return True
    except ValueError:
        pass
    try:
        validate_law_id(node_id)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def v01_node_id_format(nodes: list[dict]) -> CheckResult:
    bad: list[str] = []
    for n in nodes:
        nid = n.get("id", "")
        if not _id_is_valid(nid):
            bad.append(nid)
            if len(bad) > 10:
                break
    return CheckResult(
        "V01", "All node ids match ARTICLE_KEY_RE or LAW_ID_RE",
        "FAIL", not bad,
        details=f"{len(bad)} bad ids: {bad[:5]}" if bad else "ok",
    )


def v02_contains_endpoints_in_nodes(nodes: list[dict], contains: list[dict]) -> CheckResult:
    node_ids = {n["id"] for n in nodes}
    bad: list[tuple[str, str]] = []
    for e in contains:
        if e["source"] not in node_ids or e["target"] not in node_ids:
            bad.append((e["source"], e["target"]))
            if len(bad) > 5:
                break
    return CheckResult(
        "V02", "All CONTAINS edges' source/target appear in nodes",
        "FAIL", not bad,
        details=f"{len(bad)} dangling: {bad[:3]}" if bad else "ok",
    )


def v03_contains_no_cycle(nodes: list[dict], contains: list[dict]) -> CheckResult:
    """Topological-sort the CONTAINS DAG."""
    node_ids = {n["id"] for n in nodes}
    in_deg: dict[str, int] = defaultdict(int)
    children: dict[str, list[str]] = defaultdict(list)
    for e in contains:
        children[e["source"]].append(e["target"])
        in_deg[e["target"]] += 1
    # Kahn's algorithm
    queue = [n for n in node_ids if in_deg[n] == 0]
    visited = 0
    while queue:
        u = queue.pop()
        visited += 1
        for c in children.get(u, []):
            in_deg[c] -= 1
            if in_deg[c] == 0:
                queue.append(c)
    cycles = len(node_ids) - visited
    return CheckResult(
        "V03", "CONTAINS graph is a DAG (no cycles)",
        "FAIL", cycles == 0,
        details=f"{cycles} nodes in cycles" if cycles else "ok",
    )


def v04_unique_parent(nodes: list[dict], contains: list[dict]) -> CheckResult:
    parent_count: dict[str, int] = defaultdict(int)
    for e in contains:
        parent_count[e["target"]] += 1
    multi_parent = [(n, c) for n, c in parent_count.items() if c > 1]
    laws = {n["id"] for n in nodes if n.get("type") == "Law"}
    no_parent = [n["id"] for n in nodes if n["id"] not in laws
                 and parent_count.get(n["id"], 0) == 0]
    bad = bool(multi_parent or no_parent)
    return CheckResult(
        "V04", "Every non-Law node has exactly one CONTAINS parent",
        "FAIL", not bad,
        details=(f"multi-parent={len(multi_parent)}, orphan={len(no_parent)}; "
                 f"sample multi={multi_parent[:3]}, orphan={no_parent[:3]}") if bad else "ok",
    )


def v05_cites_target_in_nodes(nodes: list[dict], cites: list[dict]) -> CheckResult:
    node_ids = {n["id"] for n in nodes}
    dangling = [e for e in cites if e["target"] not in node_ids]
    return CheckResult(
        "V05", "All CITES targets exist in nodes",
        "FAIL", not dangling,
        details=f"{len(dangling)} dangling targets" if dangling else "ok",
    )


def v06_enum_usage(nodes: list[dict], all_edges: list[dict]) -> CheckResult:
    types = {n.get("type") for n in nodes}
    rels = {e.get("rel") for e in all_edges}
    expected_types = {"Law", "Article", "Paragraph", "Item",
                      "SupplArticle", "SupplParagraph", "Hierarchy", "Attachment"}
    expected_rels = {"CONTAINS", "CITES", "DELEGATES_TO",
                     "REFERS_TO_ATTACHMENT", "AMENDS"}
    missing_types = expected_types - types
    missing_rels = expected_rels - rels
    return CheckResult(
        "V06", "All declared NodeType / EdgeRel enums see at least 1 record",
        "WARN", not (missing_types or missing_rels),
        details=(f"missing types={missing_types}, missing rels={missing_rels}"
                 if (missing_types or missing_rels) else "ok"),
    )


def v07_kpi(stats: dict, totals: dict) -> CheckResult:
    """KPI gating against design doc §5."""
    failed: list[str] = []

    int_resolved = stats.get("internal_resolved_exact", 0) + stats.get(
        "internal_resolved_paragraph_to_article", 0)
    int_total = int_resolved + stats.get("internal_unresolved", 0)
    if int_total:
        rate = int_resolved / int_total
        if rate < _KPI["internal_resolution_min"]:
            failed.append(f"internal_resolution {rate:.2%} < {_KPI['internal_resolution_min']:.0%}")

    ext_resolved = stats.get("external_resolved_exact", 0) + stats.get(
        "external_resolved_paragraph_to_article", 0)
    ext_total = ext_resolved + stats.get("external_unresolved_law", 0) + stats.get(
        "external_unresolved_target", 0)
    if ext_total:
        rate = ext_resolved / ext_total
        if rate < _KPI["external_resolution_min"]:
            failed.append(f"external_resolution {rate:.2%} < {_KPI['external_resolution_min']:.0%}")

    ref_resolved = stats.get("referential_resolved", 0)
    ref_total = ref_resolved + stats.get("referential_unresolved", 0)
    if ref_total:
        rate = ref_resolved / ref_total
        if rate < _KPI["referential_resolution_min"]:
            failed.append(f"referential_resolution {rate:.2%} < {_KPI['referential_resolution_min']:.0%}")

    delegates = stats.get("delegates_total", 0)
    if delegates < _KPI["delegates_min"]:
        failed.append(f"delegates_total {delegates} < {_KPI['delegates_min']}")

    laws = totals.get("laws", 0)
    attachments = totals.get("attachments", 0)
    if laws:
        ratio = attachments / laws
        if ratio < _KPI["attachments_per_law_min"]:
            failed.append(f"attachments/law {ratio:.2f} < {_KPI['attachments_per_law_min']}")

    return CheckResult(
        "V07", "Quality KPIs meet thresholds",
        "WARN", not failed,
        details=", ".join(failed) if failed else "ok",
    )


def v08_determinism(nodes_path: Path, contains_path: Path) -> CheckResult:
    """Hash sorted line set — stable for re-runs of the same data."""
    h = hashlib.sha256()
    for p in (nodes_path, contains_path):
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            lines = sorted(line.rstrip("\n") for line in f)
        for line in lines:
            h.update(line.encode("utf-8"))
            h.update(b"\n")
    digest = h.hexdigest()
    return CheckResult(
        "V08", "Sorted-line hash present (use across runs to verify determinism)",
        "FAIL", True,
        details=f"sha256={digest[:16]}…",
    )


def v09_resolution_conservation(stats: dict) -> CheckResult:
    """Sum of resolved + unresolved by category equals raw extracted (loss = 0).

    We can't compare to extraction count without saving it; instead verify
    each bucket has internally consistent positive integers.
    """
    issues: list[str] = []
    for k, v in stats.items():
        if isinstance(v, int) and v < 0:
            issues.append(f"{k}={v}")
    return CheckResult(
        "V09", "All resolution counters non-negative",
        "FAIL", not issues,
        details=", ".join(issues) if issues else "ok",
    )


def v11_body_text_floor(nodes: list[dict]) -> CheckResult:
    """Body-bearing node types must have non-empty text in expected proportions.

    Catches a regression where a parser change drops body text into a
    sibling field (a non-default tag in e-Gov XML), leaving most nodes with
    header-only text. Article/SupplArticle/
    Hierarchy/Law/Attachment are excluded — empty body is by-design or
    legitimately variable.
    """
    by_type_total: dict[str, int] = defaultdict(int)
    by_type_empty: dict[str, int] = defaultdict(int)
    by_type_lens: dict[str, list[int]] = defaultdict(list)
    for n in nodes:
        t = n.get("type")
        if t not in _TEXT_FLOORS:
            continue
        by_type_total[t] += 1
        text = (n.get("text") or "").strip()
        if not text:
            by_type_empty[t] += 1
        by_type_lens[t].append(len(text))

    failed: list[str] = []
    for t, floor in _TEXT_FLOORS.items():
        total = by_type_total.get(t, 0)
        if total == 0:
            continue
        empty_pct = by_type_empty.get(t, 0) * 100.0 / total
        lens = sorted(by_type_lens[t])
        p50 = lens[len(lens) // 2] if lens else 0
        if empty_pct > floor["empty_pct_max"]:
            failed.append(f"{t} empty {empty_pct:.2f}% > {floor['empty_pct_max']}%")
        if p50 < floor["len_p50_min"]:
            failed.append(f"{t} len_p50 {p50} < {floor['len_p50_min']}")

    return CheckResult(
        "V11", "Body-bearing node types meet empty-rate and length floors",
        "FAIL", not failed,
        details=", ".join(failed) if failed else "ok",
    )


def v10_no_duplicate_node_ids(nodes: list[dict]) -> CheckResult:
    """Detect duplicate node IDs in jp_nodes.jsonl.

    Each node ID must be unique across the whole graph; cross-version emission
    or parser bugs typically surface here first.
    """
    seen: set[str] = set()
    dups: list[str] = []
    for n in nodes:
        nid = n["id"]
        if nid in seen:
            dups.append(nid)
            if len(dups) > 5:
                break
        seen.add(nid)
    return CheckResult(
        "V10", "All node IDs are unique",
        "FAIL", not dups,
        details=f"{len(dups)} duplicate ids: {dups[:3]}" if dups else "ok",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="JLaw-CiteGraph graph validator (v2.0)")
    ap.add_argument("--data", required=True, type=Path,
                    help="data/parsed directory")
    ap.add_argument("--kpi", action="store_true",
                    help="Treat KPI gating (V07) as FAIL severity")
    args = ap.parse_args()

    nodes_fp = args.data / "jp_nodes.jsonl"
    contains_fp = args.data / "jp_contains_edges.jsonl"
    cites_fp = args.data / "jp_cites_edges.jsonl"
    delegates_fp = args.data / "jp_delegates_edges.jsonl"
    attaches_fp = args.data / "jp_attaches_edges.jsonl"
    amends_fp = args.data / "jp_amends_edges.jsonl"
    cites_stats_fp = args.data / "jp_cites_stats.json"
    parse_stats_fp = args.data / "jp_parse_stats.json"

    if not nodes_fp.exists() or not contains_fp.exists():
        print(f"[validate] Required files missing: {nodes_fp}, {contains_fp}",
              file=sys.stderr)
        return 2

    print(f"[validate] Loading {nodes_fp.name}…", file=sys.stderr)
    nodes = _load_jsonl(nodes_fp)
    contains = _load_jsonl(contains_fp)
    cites = _load_jsonl(cites_fp) if cites_fp.exists() else []
    delegates = _load_jsonl(delegates_fp) if delegates_fp.exists() else []
    attaches = _load_jsonl(attaches_fp) if attaches_fp.exists() else []
    amends = _load_jsonl(amends_fp) if amends_fp.exists() else []
    all_edges = contains + cites + delegates + attaches + amends

    cites_stats = json.loads(cites_stats_fp.read_text(encoding="utf-8")) \
        if cites_stats_fp.exists() else {}
    totals = json.loads(parse_stats_fp.read_text(encoding="utf-8")).get("totals", {}) \
        if parse_stats_fp.exists() else {}

    checks: list[CheckResult] = [
        v01_node_id_format(nodes),
        v02_contains_endpoints_in_nodes(nodes, contains),
        v03_contains_no_cycle(nodes, contains),
        v04_unique_parent(nodes, contains),
        v05_cites_target_in_nodes(nodes, cites),
        v06_enum_usage(nodes, all_edges),
        v07_kpi(cites_stats, totals),
        v08_determinism(nodes_fp, contains_fp),
        v09_resolution_conservation(cites_stats),
        v10_no_duplicate_node_ids(nodes),
        v11_body_text_floor(nodes),
    ]

    print()
    print(f"  {'ID':<5} {'SEV':<5} {'STATUS':<7} DESCRIPTION")
    print(f"  {'─' * 5} {'─' * 5} {'─' * 7} {'─' * 60}")
    fail = False
    for c in checks:
        status = "PASS" if c.passed else "FAIL"
        sev = c.severity
        if not c.passed:
            if sev == "FAIL" or (args.kpi and c.id == "V07"):
                fail = True
        print(f"  {c.id:<5} {sev:<5} {status:<7} {c.description}")
        if c.details and (not c.passed or c.id == "V08"):
            print(f"        └─ {c.details}")

    print()
    print(f"[validate] {'FAIL' if fail else 'OK'}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
