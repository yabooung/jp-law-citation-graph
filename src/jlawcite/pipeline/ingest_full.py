"""Full-corpus ingestion: walk e-Gov XML directory → graph JSONL (v2.0).

See `docs/GRAPH_SCHEMA_V2.md` for the authoritative schema.

Usage:
    jlawcite build \
        --input data/raw/law_xml \
        --csv data/raw/law_xml/all_law_list.csv \
        --output data/parsed

Outputs:
    data/parsed/jp_nodes.jsonl          — Law / Hierarchy / Article / Paragraph /
                                          Item / SupplArticle / SupplParagraph /
                                          Attachment
    data/parsed/jp_contains_edges.jsonl — strict tree (Law-rooted)
    data/parsed/jp_cites_edges.jsonl    — citations (Phase 3 enhances resolution)
    data/parsed/jp_parse_stats.json     — per-law stats
    data/parsed/jp_cites_stats.json     — citation resolution stats
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from tqdm import tqdm

from jlawcite.citation import (
    extract_amendments,
    extract_attachment_refs,
    extract_delegations,
    extract_external,
    extract_internal,
    ENUM_GAP_PAT,
    extract_referential,
)
from jlawcite.resolver import (
    LawNameIndex,
    build_law_contexts,
    section_key,
    extract_abbrev_definitions,
    resolve_abbrev_definition,
    is_amending_law_name,
    ABBREV_PRE_AMENDMENT,
    ABBREV_AMENDING,
    load_aliases,
    normalize_promulgation,
    resolve_referential,
)
from jlawcite.parser import list_law_versions, parse_law_xml, split_current_pending

_DEFAULT_ALIAS_PATH = Path(__file__).resolve().parent.parent / "jp_law_aliases.json"


NAKED_ANAPHORA = {"法", "法律", "令", "施行令", "施行規則", "規則", "省令"}

# Short law tokens from NAKED_LAW_PAT (see citation_extractor).
_SAME_AS_LAST = {"同法", "同令", "同規則", "同省令", "同府令", "同条例"}
_AMENDED = {"新法": "法", "新令": "令", "新規則": "規則"}
_PRE_AMENDMENT = {"旧法", "旧令", "旧規則"}

# law_id type code → which bare token names the law itself.
def _self_token(law_id: str) -> str:
    code = law_id[3:5]
    if code == "AC":
        return "法"
    if code == "CO":
        return "令"
    return "規則"


# 同法 names an Act, 同令 an order, 同規則/同省令/同府令 a ministerial rule:
# the antecedent is the latest external law *of that kind* in the text.
_SAME_KIND = {
    "同法": lambda lid: lid[3:5] == "AC",
    "同令": lambda lid: lid[3:5] != "AC",
    "同規則": lambda lid: lid[3:5] not in ("AC", "CO"),
    "同省令": lambda lid: lid[3:5] not in ("AC", "CO"),
    "同府令": lambda lid: lid[3:5] not in ("AC", "CO"),
    "同条例": lambda lid: True,
}


def _resolve_naked(er, src_law_id, ext_history, family_index, reverse_family):
    """Resolve a NAKED_LAW_PAT token. Returns (ResolvedLaw | None, skip_reason | None).
    `ext_history` lists the law_ids of the text's resolved external citations
    so far, in order."""
    from jlawcite.resolver import ResolvedLaw
    name = er.law_name_raw
    if name in _SAME_AS_LAST:
        ok = _SAME_KIND.get(name, lambda lid: True)
        hit = next((lid for lid in reversed(ext_history) if ok(lid)), None)
        if hit:
            return ResolvedLaw(hit, 0.85, "same_as_last"), None
        return None, None
    if name in _PRE_AMENDMENT:
        # Text before amendment — not in the corpus (only the current version is).
        return None, "pre_amendment"
    base = _AMENDED.get(name, name)
    if name in _AMENDED and base == _self_token(src_law_id):
        return ResolvedLaw(src_law_id, 0.85, "amended_self"), None
    return _resolve_naked_anaphora_family(base, src_law_id, family_index, reverse_family), None


def _resolve_naked_anaphora_family(
    naked_name: str,
    src_law_id: str,
    family_index: dict,
    reverse_family: dict,
):
    """v2.2 anaphora cross-family — naked '法/令/施行令' 등을 source family transform.

    - source 가 child (시행령/시행규칙) + naked '法' → parent (모법) 로 resolve
    - source 가 parent (모법) + naked '令/施行令' → 政令 child 로 resolve
    - source 가 parent + naked '規則/施行規則' → 省令 child 로 resolve
    - source 가 child + naked sibling kind → 같은 parent 의 다른 child (sibling)
    """
    from jlawcite.resolver import ResolvedLaw
    if naked_name not in NAKED_ANAPHORA:
        return None
    if naked_name in {"法", "法律"}:
        parent = reverse_family.get(src_law_id)
        if parent:
            return ResolvedLaw(parent, 0.85, "anaphora_family")
        return None
    if naked_name in {"令", "施行令"}:
        target = family_index.get(src_law_id, {}).get("政令")
        if target:
            return ResolvedLaw(target, 0.85, "anaphora_family")
    if naked_name in {"規則", "施行規則", "省令"}:
        target = family_index.get(src_law_id, {}).get("省令")
        if target:
            return ResolvedLaw(target, 0.85, "anaphora_family")
    parent = reverse_family.get(src_law_id)
    if parent:
        if naked_name in {"令", "施行令"}:
            target = family_index.get(parent, {}).get("政令")
            if target and target != src_law_id:
                return ResolvedLaw(target, 0.80, "anaphora_family")
        if naked_name in {"規則", "施行規則", "省令"}:
            target = family_index.get(parent, {}).get("省令")
            if target and target != src_law_id:
                return ResolvedLaw(target, 0.80, "anaphora_family")
    return None


def _load_old_names_from_csv(csv_fp: Path) -> dict[str, str]:
    """Read CSV col[4] '旧法令名' and map each previous name → current law_id.

    Returns dict[old_name → law_id]. Multiple comma-separated old names per
    row are split. Conflicts are resolved by latest 施行日 (already enforced
    upstream by find_law_xmls when CSV is provided, so we just take last).
    """
    import csv as _csv
    out: dict[str, str] = {}
    if not csv_fp or not csv_fp.exists():
        return out
    with csv_fp.open(encoding="utf-8-sig") as f:
        r = _csv.reader(f)
        try:
            next(r)
        except StopIteration:
            return out
        for row in r:
            if len(row) < 13:
                continue
            old_field = row[4]
            law_id = row[11]
            if not old_field or not law_id:
                continue
            for old_name in old_field.split(","):
                old_name = old_name.strip()
                if old_name:
                    out[old_name] = law_id
    return out


# Node types that carry text and so need citation extraction.
_TEXT_BEARING = {"Paragraph", "SupplParagraph", "Item"}

# Article-equivalents (parent of paragraphs) — used as fallback target.
_ARTICLE_LEVEL = {"Article", "SupplArticle"}


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _record_to_node_dict(rec) -> dict:
    """ParsedRecord → flat node dict (matches GraphNode field set)."""
    d = {
        "id": rec.id,
        "type": rec.type,
        "title": rec.title,
        "text": rec.text or "",
        "law_id": rec.law_id,
        "parent_id": rec.parent_id,
        "section": rec.section or "main",
        "article_path": rec.article_path,
        "paragraph_num": rec.paragraph_num,
        "item_num": rec.item_num,
        "suppl_tag": rec.suppl_tag,
        "is_active": rec.is_active,
        "jurisdiction": rec.jurisdiction,
        "schema_version": "v2.0",
    }
    # Enrich from raw_attributes (mst_id, law_title, etc.)
    for k in ("mst_id", "law_title", "level", "level_path", "appdx_tag",
              "attachment_subtype", "synthetic", "promulgation_no",
              "item_path", "suppl_amend_law_num", "abbrevs"):
        if k in rec.raw_attributes:
            d[k] = rec.raw_attributes[k]
    return d


def main():
    ap = argparse.ArgumentParser(description="JP full-corpus ingest (v2.0)")
    ap.add_argument("--input", required=True, type=Path,
                    help="e-Gov XML base directory (data/raw/law_xml)")
    ap.add_argument("--csv", type=Path, default=None,
                    help="all_law_list.csv (optional, improves law_name)")
    ap.add_argument("--output", required=True, type=Path,
                    help="Output directory (data/parsed)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Limit number of XMLs (for testing)")
    ap.add_argument("--no-cites", action="store_true",
                    help="Skip 2-pass citation extraction (faster, edges-only)")
    ap.add_argument("--aliases", type=Path, default=_DEFAULT_ALIAS_PATH,
                    help="Path to law alias JSON (default: src/jlawcite/jp_law_aliases.json)")
    ap.add_argument("--dump-unresolved", action="store_true",
                    help="Write jp_unresolved_cites.jsonl (every unresolved citation with "
                         "context) for diagnosis")
    ap.add_argument("--as-of", default=date.today().strftime("%Y%m%d"),
                    help="YYYYMMDD reference date: ingest the version in force on this "
                         "date; later versions go to jp_pending_versions.jsonl (default: today)")
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # ---------- Load resolver assets ----------
    aliases = load_aliases(args.aliases) if args.aliases else {}
    print(f"[ingest] Loaded {len(aliases)} aliases from {args.aliases}", file=sys.stderr)

    old_names = _load_old_names_from_csv(args.csv) if args.csv else {}
    print(f"[ingest] Loaded {len(old_names)} 旧法令名 mappings from CSV",
          file=sys.stderr)

    # ---------- Pass 1: parse all XMLs ----------
    all_records: list[dict] = []
    all_contains_edges: list[dict] = []
    all_stats: list[dict] = []
    law_name_to_id: dict[str, str] = {}
    promulgation_to_id: dict[str, str] = {}

    # v2 specificity-aware index, scoped so 本則 and each 附則 block never mix:
    # scope + (art_path,)                    → Article id
    # scope + (art_path, pnum)               → Paragraph id
    # scope + (art_path, pnum, item_path)    → Item id
    # scope = ("M", law_id) for 本則, ("S", law_id, suppl_tag) for a 附則 block.
    article_index: dict[tuple, str] = {}
    # law_id → suppl_tag of the original (enactment) 附則, i.e. the first block
    # without AmendLawNum. 「附則第N条」 in 本則 text points there.
    original_suppl: dict[str, str] = {}
    # (law_id, annex_id) → Attachment node id
    attachment_index: dict[tuple[str, str], str] = {}

    # One version per law (in force at --as-of) goes into the graph; versions
    # with a later 施行日 are emitted as pending-amendment metadata.
    selected: list[tuple] = []
    for versions in list_law_versions(args.input, args.csv).values():
        selected.append(split_current_pending(versions, args.as_of))
    selected.sort(key=lambda t: t[0].law_id)
    if args.limit:
        selected = selected[: args.limit]

    pending_records: list[dict] = []
    for current, pending, _ in selected:
        prev = current
        for v in pending:
            pending_records.append({
                "law_id": v.law_id,
                "law_title": v.law_name,
                "mst_id": v.mst_id,
                "enforcement_date": v.enforcement_date,
                "enforcement_note": v.enforcement_note,
                "amend_law_name": v.amend_law_name,
                "amend_law_num": v.amend_law_num,
                "amend_promulgation_date": v.amend_promulgation_date,
                "supersedes_mst_id": prev.mst_id,
                "url": v.url,
                "xml_relpath": v.xml_path.relative_to(args.input).as_posix(),
            })
            prev = v

    print(f"[ingest] as_of={args.as_of}: {len(selected)} laws "
          f"({sum(1 for *_, f in selected if not f)} not yet in force), "
          f"{len(pending_records)} pending versions", file=sys.stderr)

    for current, pending, in_force in tqdm(selected, desc="Parse XML"):
        records, edges, stats = parse_law_xml(current.xml_path, current.law_name or None)
        if stats.error:
            tqdm.write(f"[skip] {xml_path.name}: {stats.error}")
            continue

        law_id = None
        for rec in records:
            if rec.type == "Law":
                law_id = rec.id
                law_name_to_id[rec.title] = law_id
                prom = rec.raw_attributes.get("promulgation_no")
                if prom:
                    norm = normalize_promulgation(prom)
                    if norm:
                        promulgation_to_id[norm] = law_id

            # Build specificity-aware index.
            if rec.law_id and rec.article_path:
                if rec.section == "suppl":
                    scope = ("S", rec.law_id, rec.suppl_tag)
                    if (rec.type == "SupplArticle"
                            and "suppl_amend_law_num" not in rec.raw_attributes):
                        original_suppl.setdefault(rec.law_id, rec.suppl_tag)
                else:
                    scope = ("M", rec.law_id)
                if rec.type in _ARTICLE_LEVEL:
                    article_index[scope + (rec.article_path,)] = rec.id
                elif rec.type in ("Paragraph", "SupplParagraph") and rec.paragraph_num:
                    article_index[scope + (rec.article_path, rec.paragraph_num)] = rec.id
                elif rec.type == "Item" and rec.paragraph_num:
                    item_path = rec.raw_attributes.get("item_path") or str(rec.item_num)
                    article_index[scope + (rec.article_path, rec.paragraph_num,
                                           item_path)] = rec.id

            if rec.type == "Attachment" and rec.law_id:
                # Reverse out the slug from the node id (`{law_id}_at-{slug}`)
                slug = rec.id.split("_at-", 1)[-1]
                attachment_index[(rec.law_id, slug)] = rec.id

            node = _record_to_node_dict(rec)
            if rec.type == "Law":
                node["enforcement_date"] = current.enforcement_date
                node["is_active"] = in_force
                node["pending_version_count"] = len(pending)
                node["next_enforcement_date"] = pending[0].enforcement_date if pending else None
            all_records.append(node)

        for src, tgt, rel in edges:
            all_contains_edges.append({"source": src, "target": tgt, "rel": rel})

        all_stats.append({
            "law_id": law_id,
            "law_name": stats.law,
            "articles": stats.articles,
            "paragraphs": stats.paragraphs,
            "items": stats.items,
            "suppl_articles": stats.suppl_articles,
            "suppl_paragraphs": stats.suppl_paragraphs,
            "suppl_items": stats.suppl_items,
            "hierarchy": stats.hierarchy,
            "attachments": stats.attachments,
            "skipped": stats.skipped,
            "dup_ids": stats.dup_ids,
        })

    # ---------- Pass 1 outputs ----------
    nodes_fp = args.output / "jp_nodes.jsonl"
    contains_fp = args.output / "jp_contains_edges.jsonl"
    stats_fp = args.output / "jp_parse_stats.json"

    write_jsonl(nodes_fp, all_records)
    write_jsonl(contains_fp, all_contains_edges)
    write_jsonl(args.output / "jp_pending_versions.jsonl", pending_records)
    stats_fp.write_text(
        json.dumps({
            "as_of": args.as_of,
            "totals": {
                "pending_versions": len(pending_records),
                "laws_not_yet_in_force": sum(1 for *_, f in selected if not f),
                "laws": sum(1 for r in all_records if r["type"] == "Law"),
                "hierarchy": sum(1 for r in all_records if r["type"] == "Hierarchy"),
                "articles": sum(1 for r in all_records if r["type"] == "Article"),
                "paragraphs": sum(1 for r in all_records if r["type"] == "Paragraph"),
                "items": sum(1 for r in all_records if r["type"] == "Item"),
                "suppl_articles": sum(1 for r in all_records if r["type"] == "SupplArticle"),
                "suppl_paragraphs": sum(1 for r in all_records if r["type"] == "SupplParagraph"),
                "attachments": sum(1 for r in all_records if r["type"] == "Attachment"),
            },
            "per_law": all_stats,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[ingest] Pass 1 done. {len(all_records):,} nodes, "
          f"{len(all_contains_edges):,} CONTAINS edges", file=sys.stderr)

    if args.no_cites:
        print("[ingest] --no-cites set, skipping CITES extraction", file=sys.stderr)
        return

    # ---------- Build resolution assets ----------
    # Official short names from LawTitle@Abbrev (激甚法 → 激甚災害に…法律).
    # A short name claimed by two laws is ambiguous and skipped.
    abbrev_claims: dict[str, set[str]] = {}
    for r in all_records:
        if r["type"] == "Law":
            for ab in r.get("abbrevs") or []:
                abbrev_claims.setdefault(ab, set()).add(r["title"])
    official = {ab: next(iter(t)) for ab, t in abbrev_claims.items()
                if len(t) == 1 and ab not in law_name_to_id}
    aliases = {**official, **aliases}   # curated aliases win
    print(f"[ingest] Official abbreviations (LawTitle@Abbrev): {len(official):,}",
          file=sys.stderr)
    name_index = LawNameIndex(
        canonical_to_id=law_name_to_id,
        promulgation_to_id=promulgation_to_id,
        alias_to_canonical=aliases,
        old_to_id=old_names,
    )
    law_contexts = build_law_contexts(all_records)

    # Per-law abbreviation definitions: law_id → {abbr: law_id | ABBREV_*}.
    # First definition in document order wins.
    abbrev_map: dict[str, dict[str, str]] = {}
    for r in all_records:
        if r["type"] not in _TEXT_BEARING or "以下「" not in (r.get("text") or ""):
            continue
        defs = abbrev_map.setdefault(r["law_id"], {})
        for abbr, prom, name in extract_abbrev_definitions(r["text"]):
            if abbr in defs:
                continue
            target = resolve_abbrev_definition(abbr, prom, name, name_index)
            if target:
                defs[abbr] = target
    print(f"[ingest] Abbreviation definitions: "
          f"{sum(len(v) for v in abbrev_map.values()):,} across {len(abbrev_map):,} laws",
          file=sys.stderr)

    # Law family map: source_law_id → {'政令': cabinet_order_law_id, '省令': ..., ...}
    # Used by DELEGATES_TO resolution. Built from title suffix matching.
    family_index = _build_family_index(law_name_to_id)
    print(f"[ingest] Family index: {sum(len(v) for v in family_index.values())} relations",
          file=sys.stderr)

    # v2.2 — child → parent reverse map (anaphora_family 의 'naked 法' → parent resolve)
    reverse_family: dict[str, str] = {}
    for parent_id, kinds in family_index.items():
        for _kind, child_id in kinds.items():
            reverse_family[child_id] = parent_id
    print(f"[ingest] Reverse family (child→parent): {len(reverse_family)}", file=sys.stderr)

    # ---------- Pass 2: citation extraction ----------
    print("[ingest] Pass 2: extracting CITES / DELEGATES_TO / REFERS_TO_ATTACHMENT...",
          file=sys.stderr)
    delegates_edges: list[dict] = []
    attaches_edges: list[dict] = []
    amends_edges: list[dict] = []

    cites_edges: list[dict] = []
    cites_stats: dict[str, int] = {
        "internal_resolved_exact": 0,
        "internal_resolved_paragraph_to_article": 0,
        "internal_unresolved": 0,
        "external_resolved_exact": 0,
        "external_resolved_paragraph_to_article": 0,
        "external_unresolved_law": 0,         # law_name not found
        "external_unresolved_target": 0,      # law found but article not in index
        "referential_resolved": 0,
        "referential_unresolved": 0,
        "referential_self": 0,
        "by_via": {"promulgation": 0, "canonical": 0, "old_name": 0,
                   "alias": 0, "prefix_stripped": 0, "suffix": 0,
                   "anaphora_family": 0, "same_as_last": 0, "amended_self": 0},
        # Out of KPI scope (target text is not in the corpus / ambiguous):
        "external_pre_amendment": 0,          # 旧法第N条 — pre-amendment text
        "external_amending_law": 0,           # 改正法第N条 — amending acts are not in e-Gov
        "internal_amend_suppl_resolved": 0,   # 第N条 inside an amending law's 附則
        "internal_amend_suppl_unresolved": 0,
    }

    text_records = [r for r in all_records if r["type"] in _TEXT_BEARING]
    unresolved_dump: list[dict] | None = [] if args.dump_unresolved else None

    def note_unresolved(kind: str, rec: dict, span: tuple[int, int], raw: str, **extra):
        if unresolved_dump is None:
            return
        t = rec["text"]
        unresolved_dump.append({"kind": kind, "source": rec["id"], "raw": raw,
                                "before": t[max(0, span[0] - 30):span[0]],
                                "after": t[span[1]:span[1] + 15], **extra})
    known_law_ids = {r["id"] for r in all_records if r["type"] == "Law"}
    law_titles = {r["id"]: r["title"] for r in all_records if r["type"] == "Law"}

    for rec in tqdm(text_records, desc="Extract cites"):
        text = rec.get("text") or ""
        if not text:
            continue
        src_law_id = rec["law_id"]
        src_key = rec["id"]
        src_section = rec.get("section") or "main"
        src_art_path = rec.get("article_path") or ""
        src_pnum = rec.get("paragraph_num")
        # In an amending law's 附則 block, bare 第N条 may mean the amending
        # law's own articles, which are not in the corpus.
        in_amend_suppl = src_section == "suppl" and bool(rec.get("suppl_amend_law_num"))
        own_suppl_scope = (("S", src_law_id, rec.get("suppl_tag")) if in_amend_suppl
                           else _suppl_scope(original_suppl, src_law_id))
        own_scope = (("S", src_law_id, rec.get("suppl_tag")) if src_section == "suppl"
                     else ("M", src_law_id))
        src_skey = section_key(rec)
        src_item_path = rec.get("item_path") or (
            str(rec["item_num"]) if rec.get("item_num") is not None else None)
        # Explicit citations in this text, for 同条/同項/同号 antecedents:
        # (span_end, scope, art_path, pnum, item_path, names_article)
        # names_article is False for 前項/次項/同項 — 同条 skips those.
        explicit: list[tuple] = []
        # (span_end, outcome) of external citations, for enumeration carryover
        # into following bare 第N条 (「会社法第十条、第十一条」). outcome is the
        # law_id, or an out-of-scope reason / _UNRESOLVED_LAW when the law of
        # the first citation could not be resolved (the rest stay external).
        # Internal citations are anchors too (_SELF), so 「附則第三条、第六条」
        # keeps the 附則 scope. Entries: (span_end, outcome, is_suppl).
        ext_anchors: list[tuple[int, str, bool]] = []

        # External refs (other laws). Track last successful external resolution
        # so 同法/同令 referential tokens can resolve to it.
        last_external_law_id: str | None = None
        ext_history: list[str] = []
        ext_refs, spans = extract_external(text)
        law_abbrevs = abbrev_map.get(src_law_id, {})
        for er in ext_refs:
            resolved, skip = _resolve_ext_name(
                er, src_law_id, ext_history, law_abbrevs,
                name_index, family_index, reverse_family)
            if skip:
                cites_stats[f"external_{skip}"] = cites_stats.get(f"external_{skip}", 0) + 1
                ext_anchors.append((er.span[1], skip, er.suppl))
                continue
            if resolved is None or resolved.law_id not in known_law_ids:
                # (old-name CSV mappings can point at laws absent from the corpus)
                cites_stats["external_unresolved_law"] += 1
                note_unresolved("external_law", rec, er.span, er.raw, law_name=er.law_name_raw)
                ext_anchors.append((er.span[1], _UNRESOLVED_LAW, er.suppl))
                continue
            cites_stats["by_via"][resolved.via] = cites_stats["by_via"].get(resolved.via, 0) + 1
            last_external_law_id = resolved.law_id
            ext_history.append(resolved.law_id)
            scope = (_suppl_scope(original_suppl, resolved.law_id) if er.suppl
                     else ("M", resolved.law_id))
            explicit.append((er.span[1], scope, er.article_path, er.paragraph, er.item_path, True))
            ext_anchors.append((er.span[1], resolved.law_id, er.suppl))
            edge = _resolve_target(article_index, scope, er.article_path,
                                   er.paragraph, er.item_path)
            if edge is None:
                cites_stats["external_unresolved_target"] += 1
                note_unresolved("external_target", rec, er.span, er.raw,
                                target_law=resolved.law_id, via=resolved.via)
                continue
            tgt_id, fb = edge
            e = {
                "source": src_key, "target": tgt_id, "rel": "CITES",
                "raw": er.raw, "fallback_level": fb,
                "confidence": resolved.confidence,
                "extracted_from": f"{'NAKED_LAW_PAT' if er.naked else 'EXTERNAL_FULL_PAT'}/{resolved.via}",
            }
            if _names_pre_amendment(er.law_name_raw, law_titles.get(resolved.law_id, "")):
                # 「旧○○法第N条」「改正前の○○法第N条」: right law, but the article text
                # cited is the pre-amendment one; only the current version is in the graph.
                e["version"] = "pre_amendment"
                e["confidence"] = min(e["confidence"], 0.7)
                cites_stats["external_pre_amendment_collapsed"] = cites_stats.get(
                    "external_pre_amendment_collapsed", 0) + 1
            cites_edges.append(e)
            cites_stats[f"external_resolved_{fb}"] = cites_stats.get(
                f"external_resolved_{fb}", 0) + 1

        # Internal refs (same law)
        int_refs = extract_internal(text, mask_spans=spans)
        for ir in int_refs:
            carry, carry_suppl = _enum_carry(text, ir.span[0], ext_anchors)
            suppl = ir.suppl or carry_suppl
            if carry in _OUT_OF_SCOPE:
                cites_stats[f"external_{carry}"] += 1
                ext_anchors.append((ir.span[1], carry, suppl))
                continue
            if carry == _UNRESOLVED_LAW:
                cites_stats["external_unresolved_law"] += 1
                note_unresolved("external_law", rec, ir.span, ir.raw, law_name="(enum carryover)")
                ext_anchors.append((ir.span[1], carry, suppl))
                continue
            if carry and carry != _SELF:
                # Enumerated continuation of an external citation.
                scope = (_suppl_scope(original_suppl, carry) if suppl else ("M", carry))
                explicit.append((ir.span[1], scope, ir.article_path, ir.paragraph,
                                 ir.item_path, True))
                ext_anchors.append((ir.span[1], carry, suppl))
                edge = _resolve_target(article_index, scope, ir.article_path,
                                       ir.paragraph, ir.item_path)
                if edge is None:
                    cites_stats["external_unresolved_target"] += 1
                    continue
                tgt_id, fb = edge
                cites_edges.append({
                    "source": src_key, "target": tgt_id, "rel": "CITES",
                    "raw": ir.raw, "fallback_level": fb,
                    "extracted_from": "INTERNAL_PAT/enum_carryover",
                })
                cites_stats[f"external_resolved_{fb}"] = cites_stats.get(
                    f"external_resolved_{fb}", 0) + 1
                cites_stats["by_via"]["enum_carryover"] = cites_stats["by_via"].get(
                    "enum_carryover", 0) + 1
                continue
            scope = own_suppl_scope if suppl else ("M", src_law_id)
            explicit.append((ir.span[1], scope, ir.article_path, ir.paragraph, ir.item_path, True))
            ext_anchors.append((ir.span[1], _SELF, suppl))
            edge = _resolve_target(article_index, scope, ir.article_path,
                                   ir.paragraph, ir.item_path)
            # Citations inside an amending law's 附則 block are kept out of the
            # KPI: bare 第N条 may denote the amending law's own article, and
            # 附則第N条 its own 附則, which e-Gov usually carries only as 抄.
            # Bare 第N条 edges (usually the 改正規定 target in this law) are
            # kept but flagged with lower confidence.
            ambiguous = in_amend_suppl and not suppl
            if edge is None:
                cites_stats["internal_amend_suppl_unresolved" if in_amend_suppl
                            else "internal_unresolved"] += 1
                if not in_amend_suppl:
                    note_unresolved("internal", rec, ir.span, ir.raw, suppl=suppl)
                continue
            tgt_id, fb = edge
            e = {
                "source": src_key, "target": tgt_id, "rel": "CITES",
                "raw": ir.raw, "fallback_level": fb,
                "extracted_from": "INTERNAL_PAT/amend_suppl" if ambiguous else "INTERNAL_PAT",
            }
            if ambiguous:
                # ~40% correct in a 10-edge hand-labelled sample (v3.2 evaluation)
                e["confidence"] = 0.4
            if in_amend_suppl:
                cites_stats["internal_amend_suppl_resolved"] += 1
            else:
                cites_stats[f"internal_resolved_{fb}"] = cites_stats.get(
                    f"internal_resolved_{fb}", 0) + 1
            cites_edges.append(e)

        # Attachment refs (別表第N / 様式第N) — emit REFERS_TO_ATTACHMENT
        for ar in extract_attachment_refs(text, mask_spans=spans):
            tgt_id = attachment_index.get((src_law_id, ar.attachment_slug))
            if tgt_id:
                attaches_edges.append({
                    "source": src_key, "target": tgt_id,
                    "rel": "REFERS_TO_ATTACHMENT",
                    "raw": ar.raw,
                    "extracted_from": "ATTACHMENT_REF_PAT",
                })
                cites_stats["attaches_resolved"] = cites_stats.get(
                    "attaches_resolved", 0) + 1
            else:
                cites_stats["attaches_unresolved"] = cites_stats.get(
                    "attaches_unresolved", 0) + 1

        # Delegations (政令で定める / 省令で定める …) — emit DELEGATES_TO
        for dr in extract_delegations(text, mask_spans=spans):
            tgt_law_id = family_index.get(src_law_id, {}).get(dr.target_kind)
            if tgt_law_id:
                delegates_edges.append({
                    "source": src_key, "target": tgt_law_id,
                    "rel": "DELEGATES_TO",
                    "raw": dr.raw,
                    "fallback_level": "law_only",
                    "extracted_from": f"DELEGATION/{dr.target_kind}",
                })
                cites_stats["delegates_resolved"] = cites_stats.get(
                    "delegates_resolved", 0) + 1
            else:
                cites_stats["delegates_unresolved"] = cites_stats.get(
                    "delegates_unresolved", 0) + 1

        # AMENDS — only meaningful when source is a Suppl* node.
        if rec["type"] in ("SupplArticle", "SupplParagraph"):
            for am in extract_amendments(text):
                art_path = "-".join([str(am.article_num)] + [str(e) for e in am.eda]) \
                           if am.eda else str(am.article_num)
                edge = _resolve_target(article_index, ("M", src_law_id), art_path,
                                       am.paragraph, None)
                if edge is None:
                    cites_stats["amends_unresolved"] = cites_stats.get(
                        "amends_unresolved", 0) + 1
                    continue
                tgt_id, fb = edge
                amends_edges.append({
                    "source": src_key, "target": tgt_id, "rel": "AMENDS",
                    "raw": am.raw, "fallback_level": fb,
                    "extracted_from": "AMEND_PAT",
                })
                cites_stats["amends_resolved"] = cites_stats.get(
                    "amends_resolved", 0) + 1

        # Referential refs (前条 / 同項 / 同法 / 新法 / etc.)
        if src_art_path:
            explicit.sort()
            ctx = law_contexts.get((src_law_id, src_skey))
            for ref in extract_referential(text, mask_spans=spans):
                if ref.kind in _SELF_OR_MODIFIER:
                    # 本条/本項 (self) and 各号 (「次の各号」「第一項各号」 modifier)
                    cites_stats["referential_self"] += 1
                    continue
                targets = _resolve_referential_ref(
                    ref, explicit, own_scope, src_art_path, src_pnum, src_item_path,
                    ctx, article_index)
                if targets is None:
                    resolved = resolve_referential(
                        ref.kind, src_law_id, src_skey, src_art_path, src_pnum,
                        law_contexts,
                        last_external_law_id=last_external_law_id,
                        src_item_path=src_item_path,
                    )
                    targets = [(resolved.target_id, resolved.fallback_level)] if resolved else []
                if not targets:
                    cites_stats["referential_unresolved"] += 1
                    note_unresolved("referential", rec, ref.span, ref.raw)
                    continue
                for tgt_id, fb in targets:
                    cites_edges.append({
                        "source": src_key, "target": tgt_id, "rel": "CITES",
                        "raw": ref.raw, "fallback_level": fb,
                        "extracted_from": f"REFERENTIAL/{ref.kind}",
                    })
                cites_stats["referential_resolved"] += 1

    # Dedup by (source, target, rel)
    seen = set()
    deduped = []
    for e in cites_edges:
        k = (e["source"], e["target"], e["rel"])
        if k not in seen:
            seen.add(k)
            deduped.append(e)

    cites_fp = args.output / "jp_cites_edges.jsonl"
    write_jsonl(cites_fp, deduped)

    # Dedup the rel-specific edge sets too (separate output files per rel)
    delegates_dedup = _dedup_edges(delegates_edges)
    attaches_dedup = _dedup_edges(attaches_edges)
    amends_dedup = _dedup_edges(amends_edges)
    write_jsonl(args.output / "jp_delegates_edges.jsonl", delegates_dedup)
    write_jsonl(args.output / "jp_attaches_edges.jsonl", attaches_dedup)
    write_jsonl(args.output / "jp_amends_edges.jsonl", amends_dedup)

    if unresolved_dump is not None:
        write_jsonl(args.output / "jp_unresolved_cites.jsonl", unresolved_dump)

    cites_stats["total_edges_raw"] = len(cites_edges)
    cites_stats["total_edges_deduped"] = len(deduped)
    cites_stats["delegates_total"] = len(delegates_dedup)
    cites_stats["attaches_total"] = len(attaches_dedup)
    cites_stats["amends_total"] = len(amends_dedup)
    (args.output / "jp_cites_stats.json").write_text(
        json.dumps(cites_stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ingest] Pass 2 done. "
          f"CITES={len(deduped):,} (raw {len(cites_edges):,}), "
          f"DELEGATES_TO={len(delegates_dedup):,}, "
          f"REFERS_TO_ATTACHMENT={len(attaches_dedup):,}, "
          f"AMENDS={len(amends_dedup):,}", file=sys.stderr)


def _dedup_edges(edges: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for e in edges:
        k = (e["source"], e["target"], e["rel"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


# Suffix patterns that map a parent statute name to its delegated forms.
_FAMILY_SUFFIX_TO_KIND: list[tuple[str, str]] = [
    # ('施行令', '政令') — Cabinet Order delegated by an Act
    ("施行令", "政令"),
    ("施行規則", "省令"),  # often called 省令; some are 内閣府令
    ("施行細則", "規則"),
]


def _build_family_index(name_to_id: dict[str, str]) -> dict[str, dict[str, str]]:
    """Map source_law_id → {target_kind: target_law_id} for DELEGATES_TO.

    Heuristic: '○○法施行令' is the 政令 family member of '○○法'.
    """
    out: dict[str, dict[str, str]] = {}
    for name, lid in name_to_id.items():
        for suffix, kind in _FAMILY_SUFFIX_TO_KIND:
            if not name.endswith(suffix):
                continue
            base = name[: -len(suffix)]
            parent_id = name_to_id.get(base)
            if parent_id and parent_id != lid:
                out.setdefault(parent_id, {})[kind] = lid
    return out


_SELF_OR_MODIFIER = {"本条", "本項", "本法", "本令", "本規則", "各号"}


def _resolve_referential_ref(ref, explicit, own_scope, src_art_path, src_pnum,
                             src_item_path, ctx, index) -> list[tuple[str, str]] | None:
    """Structural referential tokens. Returns [(target_id, fallback_level)]
    ([] = unresolved), or None when the token is not handled here (law-level
    tokens like 同法/新法 go to resolve_referential).

    同条/同項/同号 refer to the nearest preceding explicit citation in the same
    text (「第十条…同条第二項」); without one they fall back to the source's
    own article / paragraph. 前条/次条/前項/次項/前号/次号 navigate the
    source's own 本則 or 附則 block. A trailing locator (同条第二項) narrows
    the target. Resolved 同条/同項 become antecedents for later tokens.
    """
    kind = ref.kind
    before = [e for e in explicit if e[0] <= ref.span[0]]
    prev = before[-1] if before else None
    # 同条 means the last *article* named: in 「第二十五条…準用する。この場合に
    # おいて、前項…同条第二項」 the antecedent is 第二十五条, not 前項's article.
    prev_article = next((e for e in reversed(before) if e[5]), None)

    def resolve(scope, art, pnum, item):
        hit = _resolve_target(index, scope, art, pnum, item)
        if hit:
            explicit.append((ref.span[1], scope, art, pnum, item,
                             kind in ("同条", "前条", "次条")))
            explicit.sort()
        return [hit] if hit else []

    if kind == "同条":
        scope, art = ((prev_article[1], prev_article[2]) if prev_article
                      else (own_scope, src_art_path))
        return resolve(scope, art, ref.paragraph, ref.item_path)
    if kind == "同項":
        if prev and prev[3] is not None:
            return resolve(prev[1], prev[2], prev[3], ref.item_path)
        if src_pnum is None:
            return []
        return resolve(own_scope, src_art_path, src_pnum, ref.item_path)
    if kind == "同号":
        if prev and prev[4] is not None:
            return resolve(prev[1], prev[2], prev[3], prev[4])
        return []

    if ctx is None:
        return None if kind not in ("前条", "次条", "前項", "次項", "前各号") else []
    if kind in ("前条", "次条"):
        idx = ctx.art_path_to_idx.get(src_art_path)
        if idx is None:
            return []
        new_idx = idx + (-1 if kind == "前条" else 1)
        if not 0 <= new_idx < len(ctx.article_paths):
            return []
        tgt_path = ctx.article_paths[new_idx]
        # 抄 (excerpted) 附則 blocks skip articles: 附則第十四条's 前条 must be
        # 第十三条, not whatever excerpted article happens to precede it.
        if not _adjacent_articles(tgt_path, src_art_path) if kind == "前条"                 else not _adjacent_articles(src_art_path, tgt_path):
            return []
        return resolve(own_scope, tgt_path, ref.paragraph, ref.item_path)
    if kind in ("前項", "次項"):
        paras = ctx.paragraph_ids_by_path.get(src_art_path, [])
        idx = next((i for i, (pn, _) in enumerate(paras) if pn == src_pnum), None)
        if idx is None:
            return []
        new_idx = idx + (-1 if kind == "前項" else 1)
        if not 0 <= new_idx < len(paras):
            return []
        return resolve(own_scope, src_art_path, paras[new_idx][0], ref.item_path)
    if kind == "前各号":
        # In an Item: every earlier sibling Item (「前各号に掲げるもののほか」).
        items = ctx.item_ids_by_para.get((src_art_path, src_pnum), [])
        idx = next((i for i, (ip, _) in enumerate(items) if ip == src_item_path), None)
        if not idx:
            return []
        return [(iid, "exact") for _, iid in items[:idx]]
    return None


def _adjacent_articles(prev_path: str, next_path: str) -> bool:
    """True if article `next_path` can directly follow `prev_path`
    (10 → 11, 10 → 10-2, 10-2 → 10-3, 10-2 → 11). 第0条 (synthetic) never."""
    a = [int(x) for x in prev_path.split("-")]
    b = [int(x) for x in next_path.split("-")]
    if a[0] == 0 or b[0] == 0:
        return False
    if b[0] == a[0] + 1 and len(b) == 1:
        return True
    return b[0] == a[0] and len(b) > 1 and b > a


def _resolve_ext_name(er, src_law_id, ext_history, law_abbrevs,
                      name_index, family_index, reverse_family):
    """Resolve the law named by an external ref. Returns (ResolvedLaw | None,
    out-of-scope reason | None). Order: the source law's own abbreviation
    definitions → short-token rules (法/同法/新法) → global name index."""
    from jlawcite.resolver import ResolvedLaw
    name = er.law_name_raw
    naked = er.naked

    defined = law_abbrevs.get(name)
    if defined == ABBREV_PRE_AMENDMENT:
        return None, "pre_amendment"
    if defined == ABBREV_AMENDING:
        return None, "amending_law"
    if defined:
        return ResolvedLaw(defined, 0.95, "defined_abbrev"), None

    if naked:
        return _resolve_naked(er, src_law_id, ext_history,
                              family_index, reverse_family)
    # v2.2 anaphora cross-family — naked '法/令' 우선 시도
    resolved = _resolve_naked_anaphora_family(name, src_law_id, family_index, reverse_family)
    if resolved is None:
        resolved = name_index.resolve(name, er.promulgation)
    if resolved is None and is_amending_law_name(name):
        return None, "amending_law"
    return resolved, None


_UNRESOLVED_LAW = "unresolved_law"
_OUT_OF_SCOPE = {"pre_amendment", "amending_law"}
_SELF = "self"


_PRE_AMENDMENT_PREFIX = re.compile(r"(?:改正前の?|廃止前の?|旧)$")


def _names_pre_amendment(raw_name: str, title: str) -> bool:
    """True if the cited name puts 旧 / 改正前の directly before the resolved law's
    title (「改正前の消防法」, 「旧不動産登記法」); a title that itself starts with
    旧 (旧令による共済組合等…) does not count."""
    if not title:
        return False
    k = raw_name.rfind(title)
    return k > 0 and bool(_PRE_AMENDMENT_PREFIX.search(raw_name[:k].rstrip()))


def _enum_carry(text: str, start: int,
                anchors: list[tuple[int, str, bool]]) -> tuple[str | None, bool]:
    """(outcome, is_suppl) of the citation that a bare 第N条 at `start`
    continues, if only enumeration connectors / parentheticals separate them;
    (None, False) otherwise. outcome is a law_id, _SELF, or a skip reason."""
    best = None
    for anchor in anchors:
        if anchor[0] <= start and (best is None or anchor[0] > best[0]):
            best = anchor
    if best and ENUM_GAP_PAT.match(text[best[0]:start]):
        return best[1], best[2]
    return None, False


def _suppl_scope(original_suppl: dict[str, str], law_id: str) -> tuple | None:
    tag = original_suppl.get(law_id)
    return ("S", law_id, tag) if tag else None


def _resolve_target(
    index: dict[tuple, str],
    scope: tuple | None,
    art_path: str,
    pnum: int | None,
    item_path: str | None,
) -> tuple[str, str] | None:
    """Specificity-aware lookup. See docs §4.1.

    Returns (target_id, fallback_level) or None.
    Fallback levels: 'exact' | 'paragraph_to_article' | 'law_only'.

    Note: 'law_only' fallback is intentionally NOT used here in Phase 2 —
    Phase 3 wires that in along with promulgation matching. For now,
    Article-level fallback is the lowest specificity.
    """
    if scope is None:
        return None
    # Item exact
    if pnum is not None and item_path is not None:
        tgt = index.get(scope + (art_path, pnum, item_path))
        if tgt:
            return tgt, "exact"
    # Paragraph exact
    if pnum is not None:
        tgt = index.get(scope + (art_path, pnum))
        if tgt:
            return tgt, "exact"
    # Article-level (either pnum was None, or specific paragraph not found)
    tgt = index.get(scope + (art_path,))
    if tgt:
        # Distinguish "paragraph requested but only article known" from
        # "article-only request"
        fb = "paragraph_to_article" if pnum is not None else "exact"
        return tgt, fb
    return None


if __name__ == "__main__":
    main()
