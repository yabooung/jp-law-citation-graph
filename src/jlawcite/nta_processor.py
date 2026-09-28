"""NTA 質疑応答事例 → gold dataset.

**Generalized**: works on any nodes index (not hardcoded to 21-law).

Pipeline:
    1. Build law_name → LawID index (from CSV + alias table)
    2. Build (LawID, art_path_p_num) → article_key index (from parsed nodes)
    3. For each NTA case:
        - parse kankeihrei items
        - resolve each ref → article_key | EXTERNAL:law_name | UNRESOLVED

Output format matches data_jp/gold/gold_jp_v1.jsonl exactly.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from .citation import parse_kankeihrei

# 통達/조약 prefixes — treat as EXTERNAL terminal
EXTERNAL_LAW_PATTERNS = ("通達", "条約", "基本通達")

# Manual alias for common NTA abbreviations (extend as needed)
DEFAULT_ALIAS: dict[str, str] = {
    "一般社団法": "一般社団法人及び一般財団法人に関する法律",
    "特定調停法": "特定債務等の調整の促進のための特定調停に関する法律",
    "災害減免法": "災害被害者に対する租税の減免、徴収猶予等に関する法律",
    "措置法": "租税特別措置法",
    "通則法": "国税通則法",
    "徴収法": "国税徴収法",
    "印紙法": "印紙税法",
    "所税法": "所得税法",
    "法税法": "法人税法",
    "消税法": "消費税法",
    "相税法": "相続税法",
    "評価法": "資産評価法",
}


def build_law_name_index(csv_fp: Path) -> dict[str, str]:
    """name → LawID (latest 施行日 wins).

    Reads all_law_list.csv from e-Gov dump.
    """
    cands: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with csv_fp.open(encoding="utf-8-sig") as f:
        r = csv.reader(f)
        try:
            next(r)  # header
        except StopIteration:
            return {}
        for row in r:
            if len(row) < 13:
                continue
            name = row[2]
            law_id = row[11]
            sehkoubi = row[9] or "00000000"
            cands[name].append((sehkoubi, law_id))
    return {n: max(v)[1] for n, v in cands.items()}


def build_node_index(nodes_jsonl: Path) -> dict[tuple[str, str], str]:
    """(LawID, 'art_path_p{pnum}') → article_key.

    Bug-fix from upstream: SupplProvision Article overwriting MainProvision.
    Strategy: 2-pass — main first, then suppl only if key absent.
    """
    idx: dict[tuple[str, str], str] = {}
    suppl_buf: list[tuple[tuple[str, str], str]] = []

    with nodes_jsonl.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            t = d.get("type")
            if t not in ("Article", "SupplArticle"):
                continue
            law_id = d.get("law_id")
            ap = d.get("article_path")
            pn = d.get("paragraph_num", 1)
            if not (law_id and ap):
                continue
            key = (law_id, f"{ap}_p{pn}")
            if t == "Article":
                idx[key] = d["id"]
            else:
                suppl_buf.append((key, d["id"]))

    # Suppl fills only the gaps
    for key, nid in suppl_buf:
        idx.setdefault(key, nid)

    return idx


def resolve_law_name(
    law_name: str,
    law_index: dict[str, str],
    alias: dict[str, str] | None = None,
) -> str | None:
    """Try to resolve a law_name to a LawID."""
    alias = alias or DEFAULT_ALIAS
    if law_name in law_index:
        return law_index[law_name]
    if law_name in alias:
        canonical = alias[law_name]
        if canonical in law_index:
            return law_index[canonical]
    # Fuzzy: substring match (last resort, prefer longest match)
    matches = [n for n in law_index if law_name in n or n in law_name]
    if matches:
        # Prefer exact-length match
        matches.sort(key=lambda x: abs(len(x) - len(law_name)))
        return law_index[matches[0]]
    return None


def is_external(law_name: str | None) -> bool:
    if not law_name:
        return False
    return any(p in law_name for p in EXTERNAL_LAW_PATTERNS)


def resolve_kankeihrei_to_keys(
    parsed_refs: list[dict],
    law_index: dict[str, str],
    node_index: dict[tuple[str, str], str],
    alias: dict[str, str] | None = None,
) -> dict:
    """Resolve parsed refs → article_keys / external / unresolved.

    Returns:
        {
            'gold_articles': [article_key, ...],
            'external_refs': ['EXTERNAL:law_name', ...],
            'unresolved': [raw_str, ...],
            'reasons': {'resolved_exact': N, 'external': N, 'unresolved_law': N, ...}
        }
    """
    alias = alias or DEFAULT_ALIAS
    gold: list[str] = []
    external: list[str] = []
    unresolved: list[str] = []
    reasons: dict[str, int] = defaultdict(int)

    for ref in parsed_refs:
        raw = ref.get("raw", "")
        law_name = ref.get("law_name")
        art_n = ref.get("article_num")
        eda = ref.get("eda", []) or []
        para = ref.get("paragraph") or 1

        if ref.get("parse_error"):
            unresolved.append(raw)
            reasons["parse_error"] += 1
            continue

        if is_external(law_name):
            tag = f"EXTERNAL:{law_name}"
            if tag not in external:
                external.append(tag)
            reasons["external"] += 1
            continue

        if not law_name or art_n is None:
            unresolved.append(raw)
            reasons["incomplete"] += 1
            continue

        law_id = resolve_law_name(law_name, law_index, alias)
        if not law_id:
            unresolved.append(raw)
            reasons["unresolved_law"] += 1
            continue

        # Build art_path
        if eda:
            art_path = "-".join([str(art_n)] + [str(e) for e in eda])
        else:
            art_path = str(art_n)

        key = (law_id, f"{art_path}_p{para}")
        if key in node_index:
            akey = node_index[key]
            if akey not in gold:
                gold.append(akey)
            reasons["resolved_exact"] += 1
            continue

        # Try paragraph 1 fallback
        if para != 1:
            key1 = (law_id, f"{art_path}_p1")
            if key1 in node_index:
                akey = node_index[key1]
                if akey not in gold:
                    gold.append(akey)
                reasons["resolved_p1_fallback"] += 1
                continue

        unresolved.append(raw)
        reasons["unresolved_article"] += 1

    return {
        "gold_articles": gold,
        "external_refs": external,
        "unresolved": unresolved,
        "reasons": dict(reasons),
    }


def iter_shitsugi_files(shitsugi_dir: Path) -> Iterator[Path]:
    """Yield all NTA shitsugi JSON files across zeimu sub-folders."""
    for zeimu_dir in shitsugi_dir.iterdir():
        if not zeimu_dir.is_dir():
            continue
        for fp in zeimu_dir.glob("*.json"):
            yield fp


def process_shitsugi_case(
    case: dict,
    law_index: dict[str, str],
    node_index: dict[tuple[str, str], str],
    alias: dict[str, str] | None = None,
) -> dict:
    """Process one NTA shitsugi entry → gold record.

    Input case format (NTA raw):
        {id, zeimu, url, title, shokai, kaito, kankeihrei: [str, ...], ...}

    Returns gold entry matching gold_jp_v1.jsonl format.
    """
    raw_kankeihrei = case.get("kankeihrei") or []
    parsed = parse_kankeihrei(raw_kankeihrei)
    resolved = resolve_kankeihrei_to_keys(parsed, law_index, node_index, alias)

    gold_entry = {
        "id": case.get("id", ""),
        "zeimu": case.get("zeimu", ""),
        "query": case.get("shokai", ""),
        "answer": case.get("kaito", ""),
        "title": case.get("title", ""),
        "gold_articles": resolved["gold_articles"],
        "external_refs": resolved["external_refs"],
        "unresolved": resolved["unresolved"],
        "n_total_refs": len(parsed),
        "n_resolved": len(resolved["gold_articles"]),
        "n_external": len(resolved["external_refs"]),
        "n_unresolved": len(resolved["unresolved"]),
        "reasons": resolved["reasons"],
    }
    return gold_entry
