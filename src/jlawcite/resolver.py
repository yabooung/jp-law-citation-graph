"""Citation resolution helpers (Phase 3).

See `docs/GRAPH_SCHEMA_V2.md` §4 for the authoritative rules.

Public API:
    normalize_promulgation(text) -> str
    load_aliases(path) -> dict[alias, canonical]
    LawNameIndex                                  — 3-key resolver
    ReferentialResolver                           — 前条/同項 etc. in context
    LawContext                                    — ordered article list per law

Resolution priority (LawNameIndex.resolve):
    1. promulgation_no (exact, normalized)        confidence=1.0
    2. canonical LawTitle (exact)                 confidence=1.0
    3. alias  (from JSON)                         confidence=0.9
    else None
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .numerals import kanji_to_int


# ---------------------------------------------------------------------------
# Promulgation normalization
# ---------------------------------------------------------------------------
_ERA_RE = re.compile(
    r"(明治|大正|昭和|平成|令和)"
    r"(元|[一二三四五六七八九十百千]+|\d+)年"
    r"(法律|政令|省令|府令|規則|条約|勅令|太政官布告|太政官達)"
    r"第(元|[一二三四五六七八九十百千]+|\d+)号"
)


def _to_int(token: str) -> str:
    """Convert kanji digit-string or '元' to arabic. Falls back to original."""
    if token == "元":
        return "1"
    if token.isdigit():
        return token
    n = kanji_to_int(token)
    return str(n) if n is not None else token


def normalize_promulgation(raw: str) -> str | None:
    """Normalize a promulgation-no string to a canonical key.

    '昭和四十年法律第三十三号' → '昭和40年法律第33号'
    '（昭和22年法律第26号）'  → '昭和22年法律第26号'

    Returns None if the input doesn't contain a recognizable promulgation.
    """
    if not raw:
        return None
    s = raw.strip("（）()【】 　\t\n")
    m = _ERA_RE.search(s)
    if not m:
        return None
    era = m.group(1)
    year = _to_int(m.group(2))
    kind = m.group(3)
    num = _to_int(m.group(4))
    return f"{era}{year}年{kind}第{num}号"


# ---------------------------------------------------------------------------
# Alias loading
# ---------------------------------------------------------------------------
def load_aliases(path: Path) -> dict[str, str]:
    """Load alias→canonical map. Skips keys starting with `_` (metadata).

    Conflicts (same alias → different canonicals) raise ValueError so they
    surface during ingest rather than silently breaking resolution.
    """
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if k in out and out[k] != v:
            raise ValueError(f"alias conflict: {k!r} → {out[k]!r} vs {v!r}")
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Law name resolution
# ---------------------------------------------------------------------------
@dataclass
class ResolvedLaw:
    law_id: str
    confidence: float
    via: str  # 'promulgation' | 'canonical' | 'old_name' | 'alias' | 'prefix_stripped' | 'suffix'


# Strip noise that the regex over-captures from the LEFT of a law name.
# (KR-MCP equivalent: LAW_NAME_STOPWORDS — see verify-citations.ts)
# Note: 新|旧 are intentionally NOT here — _PREFIX_STRIP below handles them
# so the resolution path can record via='prefix_stripped' (lower confidence).
_LEADING_STOPWORDS = re.compile(
    r"^(?:"
    r"の改正規定[、,]?|において準用する|により準用する|"
    r"とする|とし|の規定により|の規定による|"
    r"又は|及び|並びに|若しくは|と|や|に|から|まで|"
    r"[、,。\s]+|"
    r"前項|本条|本項|前条|次条|前号|本号|当該"
    r")+"
)

# Prefixes applied to a canonical title (mostly in 附則 / 改正法 contexts).
# Stripping these and retrying the lookup reuses the canonical index.
_PREFIX_STRIP = re.compile(
    r"^(?:新|旧|改正前の|改正後の|改正前|改正後|現行|"
    r"準用|準用する)"
)

# Non-hiragana chars that legitimately precede an over-captured law name
# (clause markers / punctuation / version prefixes). Hiragana is allowed
# separately. A kanji not in this set is treated as part of a compound law name,
# blocking the trim — this stops '失業|保険法' / '国債整理基金特別会計|法' from
# collapsing to a shorter law, while still allowing '第六十二条中|租税特別措置法'
# and version refs '旧|国民年金法' / '新|地方自治法' (same law, prior/new version).
_TRIM_BOUNDARY = set("中、。，．・／（）「」『』〕】　 \t旧新現後前")

# Trailing tokens that mark "end of law name" — used by suffix index.
_LAW_SUFFIX_TOKENS = ("法律", "法", "令", "規則", "規程", "条例", "条約", "憲法",
                      "通達", "告示", "省令", "府令", "勅令", "施行令", "施行規則")


class LawNameIndex:
    """Resolves a (law_name, promulgation) pair to (law_id, confidence).

    Resolution priority (each step independent):
        1. Promulgation no.       confidence 1.0  via='promulgation'
        2. Canonical exact         confidence 1.0  via='canonical'
        3. Old-name (旧法令名)      confidence 0.95 via='old_name'
        4. Hand alias              confidence 0.9  via='alias'
        5. Strip leading stopwords + retry  same confidence as eventual hit
        6. Strip prefix (新/旧/改正前の) + retry  -0.05 confidence
        6.5 Trim over-grab to longest known-name suffix + exact retry
                                   confidence of the exact hit (canonical/old/alias)
        7. Suffix match against canonical  confidence 0.85 via='suffix'
    """

    def __init__(
        self,
        canonical_to_id: dict[str, str],
        promulgation_to_id: dict[str, str],
        alias_to_canonical: dict[str, str],
        old_to_id: dict[str, str] | None = None,
    ) -> None:
        self.canonical_to_id = canonical_to_id
        self.promulgation_to_id = promulgation_to_id
        self.alias_to_canonical = alias_to_canonical
        self.old_to_id = old_to_id or {}
        # Suffix index — sorted longest-first so we match the most specific name.
        # Only canonical names ending in known law-suffix tokens.
        self._suffix_titles: list[str] = sorted(
            (n for n in canonical_to_id if n.endswith(_LAW_SUFFIX_TOKENS)),
            key=len, reverse=True,
        )
        # Over-grab trim anchors: full law names only (canonical ∪ 旧法令名) of
        # length >= 3. The external extractor sometimes over-captures leading
        # clutter ('第六十二条中租税特別措置法'); trimming to the longest suffix
        # that is a real law name ('租税特別措置法') both fixes the span and lets
        # resolution land exactly. Distinct lengths sorted desc → longest-first.
        # NOTE: alias keys are intentionally EXCLUDED — short generic aliases
        # ('措置法','通則法') are suffixes of many unrelated full names
        # ('社会資本整備特別措置法' etc.) and would over-trim them to the alias,
        # mis-resolving to the wrong law (precision audit 2026-06-24: 14/50
        # alias errors traced here). Genuine bare-alias uses still resolve via
        # the alias step in resolve().
        self._trim_anchors: set[str] = {
            n for n in
            (set(canonical_to_id) | set(self.old_to_id))
            if len(n) >= 3
        }
        self._trim_lengths: list[int] = sorted(
            {len(n) for n in self._trim_anchors}, reverse=True)

    # ----- Direct lookups -----
    def _direct(self, name: str) -> ResolvedLaw | None:
        lid = self.canonical_to_id.get(name)
        if lid:
            return ResolvedLaw(lid, 1.0, "canonical")
        lid = self.old_to_id.get(name)
        if lid:
            return ResolvedLaw(lid, 0.95, "old_name")
        canonical = self.alias_to_canonical.get(name)
        if canonical:
            lid = self.canonical_to_id.get(canonical)
            if lid:
                return ResolvedLaw(lid, 0.9, "alias")
        return None

    def _boundary_before(self, name: str, L: int) -> bool:
        """True if the char immediately before the L-length suffix is a legit
        over-grab boundary (clause marker / particle / punctuation), not a kanji
        that forms a compound law name.

        Guards against trimming a longer (often repealed) law name down to a
        shorter, different current law: '失業|保険法' or '国債整理基金特別会計|法'
        have a kanji boundary and must NOT be trimmed, whereas '第六十二条中|租税
        特別措置法' has a '中' boundary and is a genuine over-grab.
        """
        if L >= len(name):
            return True  # whole string is the suffix; no prefix to judge
        c = name[len(name) - L - 1]
        return c in _TRIM_BOUNDARY or ("぀" <= c <= "ゟ")  # +hiragana

    def trim_overgrab(self, name: str) -> tuple[str, int]:
        """Trim an over-captured law name to its longest known-law-name suffix.

        Returns (trimmed_name, n_prefix_chars_removed). No anchor found →
        (name, 0). Only ever returns a suffix OF `name` (never invents text),
        so it is safe: longest-match picks the most specific real law name.
        A suffix is only accepted when the preceding char is an over-grab
        boundary (see `_boundary_before`), so a compound/repealed law name is
        never collapsed to a shorter different law.

        Callers that track spans should advance the span start by the returned
        prefix length so the freed leading text (often a swallowed internal
        ref like '第六十二条中…') becomes visible to extract_internal again.
        """
        R = len(name)
        for L in self._trim_lengths:
            if L > R:
                continue
            if L < 3:
                break
            if name[-L:] in self._trim_anchors and self._boundary_before(name, L):
                return name[-L:], R - L
        return name, 0

    def _suffix_match(self, name: str) -> ResolvedLaw | None:
        """Find the longest canonical title that is a suffix of `name`.

        e.g. '新租税特別措置法' → matches '租税特別措置法'.
        Skip if the name itself is already canonical (caught earlier).
        """
        for cand in self._suffix_titles:
            if len(cand) >= len(name):
                continue  # would have matched in _direct
            if name.endswith(cand) and self._boundary_before(name, len(cand)):
                lid = self.canonical_to_id[cand]
                return ResolvedLaw(lid, 0.85, "suffix")
        return None

    def resolve(
        self,
        name_raw: str,
        promulgation: str | None = None,
    ) -> ResolvedLaw | None:
        # 1. Promulgation
        if promulgation:
            key = normalize_promulgation(promulgation)
            if key:
                lid = self.promulgation_to_id.get(key)
                if lid:
                    return ResolvedLaw(lid, 1.0, "promulgation")

        if not name_raw:
            return None

        # Canonicalize whitespace
        name = name_raw.strip()

        # 2-4. Direct lookup
        hit = self._direct(name)
        if hit:
            return hit

        # 5. Strip leading stopwords + retry
        cleaned = _LEADING_STOPWORDS.sub("", name).strip()
        if cleaned and cleaned != name:
            hit = self._direct(cleaned)
            if hit:
                return hit
            name = cleaned  # cascade for next steps

        # 6. Strip prefix (新/旧/改正前の) + retry
        stripped = _PREFIX_STRIP.sub("", name).strip()
        if stripped and stripped != name:
            hit = self._direct(stripped)
            if hit:
                # Slightly lower confidence — we modified the input
                return ResolvedLaw(hit.law_id, max(0.0, hit.confidence - 0.05),
                                   "prefix_stripped")
            name = stripped

        # 6.5 Trim over-grab to longest known-name suffix + exact retry.
        # Promotes over-captured names from fuzzy suffix (0.85) to exact
        # canonical/old_name/alias. Only fires when trimming actually shortened
        # the name (plen > 0); the trimmed string is an exact dictionary entry.
        trimmed, plen = self.trim_overgrab(name)
        if plen > 0:
            hit = self._direct(trimmed)
            if hit:
                return hit

        # 7. Suffix match against canonical
        return self._suffix_match(name)


# ---------------------------------------------------------------------------
# Referential resolution (前条 / 同項 / etc.)
# ---------------------------------------------------------------------------
@dataclass
class LawContext:
    """Per-law ordered list of (art_path, article_id) for sibling navigation.

    Built from records by `build_law_contexts`. Used to resolve 前条/次条.
    """
    law_id: str
    section: str  # 'main' or 'suppl' (suppl articles share their own sequence)
    article_paths: list[str] = field(default_factory=list)
    art_path_to_idx: dict[str, int] = field(default_factory=dict)
    article_id_by_path: dict[str, str] = field(default_factory=dict)
    paragraph_ids_by_path: dict[str, list[tuple[int, str]]] = field(
        default_factory=dict
    )  # art_path → [(pnum, paragraph_id), ...] sorted by pnum


def build_law_contexts(records: list[dict]) -> dict[tuple[str, str], LawContext]:
    """Group records by (law_id, section) and build per-group ordered structure."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        if r.get("type") not in ("Article", "Paragraph", "SupplArticle", "SupplParagraph"):
            continue
        if not r.get("law_id") or not r.get("article_path"):
            continue
        section = r.get("section") or "main"
        grouped[(r["law_id"], section)].append(r)

    out: dict[tuple[str, str], LawContext] = {}
    for (law_id, section), recs in grouped.items():
        ctx = LawContext(law_id=law_id, section=section)
        # Sort by article path's natural sequence (treat hyphenated as tuple)
        seen_paths: list[str] = []
        for r in recs:
            ap = r["article_path"]
            if r["type"] in ("Article", "SupplArticle"):
                ctx.article_id_by_path[ap] = r["id"]
                if ap not in ctx.art_path_to_idx:
                    seen_paths.append(ap)
            elif r["type"] in ("Paragraph", "SupplParagraph"):
                pnum = r.get("paragraph_num")
                if pnum:
                    ctx.paragraph_ids_by_path.setdefault(ap, []).append((pnum, r["id"]))
        seen_paths.sort(key=_art_path_sort_key)
        ctx.article_paths = seen_paths
        ctx.art_path_to_idx = {p: i for i, p in enumerate(seen_paths)}
        for ap in ctx.paragraph_ids_by_path:
            ctx.paragraph_ids_by_path[ap].sort(key=lambda t: t[0])
        out[(law_id, section)] = ctx
    return out


def _art_path_sort_key(path: str) -> tuple[int, ...]:
    """Sort '10-2' before '11', '4-3-2' before '4-4'. Non-numeric segments → 0."""
    parts = path.split("-")
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


@dataclass
class ReferentialEdge:
    target_id: str
    fallback_level: str = "exact"


def resolve_referential(
    kind: str,
    src_law_id: str,
    src_section: str,
    src_art_path: str,
    src_paragraph_num: int | None,
    contexts: dict[tuple[str, str], LawContext],
    last_external_law_id: str | None = None,
) -> ReferentialEdge | None:
    """Resolve a single referential token in context. Returns target id or None.

    Tokens handled:
        前条, 次条, 同条             → article-level (sibling navigation)
        前項, 次項, 同項             → paragraph-level
        同法, 同令, 同規則, 同条例   → last externally-cited law (Law node)
        新法, 旧法, 新令, 旧令, ...  → src law (Suppl context: amended/pre-amended)
        本条, 本項, 本法, 本令, 本規則 → self-reference (caller drops, returns None)
    Tokens not handled (require item-list context):
        同号, 前号, 前各号, 各号
    """
    if kind in ("本条", "本項", "本法", "本令", "本規則"):
        return None  # self-ref — no edge needed

    # Same-law refs — point at the last externally-cited law (Law node).
    if kind in ("同法", "同令", "同規則", "同条例"):
        if last_external_law_id:
            return ReferentialEdge(last_external_law_id, fallback_level="law_only")
        return None  # no prior external citation in this record

    # Amendment-context refs — point at the source record's own law (Law node).
    # Most common in SupplArticle text discussing the act being amended.
    if kind in ("新法", "旧法", "新令", "旧令", "新規則", "旧規則"):
        return ReferentialEdge(src_law_id, fallback_level="law_only")

    ctx = contexts.get((src_law_id, src_section))
    if ctx is None:
        return None

    if kind in ("前条", "次条", "同条"):
        if kind == "同条":
            tgt_id = ctx.article_id_by_path.get(src_art_path)
            return ReferentialEdge(tgt_id) if tgt_id else None
        idx = ctx.art_path_to_idx.get(src_art_path)
        if idx is None:
            return None
        offset = -1 if kind == "前条" else 1
        new_idx = idx + offset
        if 0 <= new_idx < len(ctx.article_paths):
            tgt_path = ctx.article_paths[new_idx]
            tgt_id = ctx.article_id_by_path.get(tgt_path)
            return ReferentialEdge(tgt_id) if tgt_id else None
        return None

    if kind in ("前項", "次項", "同項"):
        if src_paragraph_num is None:
            return None
        paras = ctx.paragraph_ids_by_path.get(src_art_path, [])
        if not paras:
            return None
        if kind == "同項":
            for pnum, pid in paras:
                if pnum == src_paragraph_num:
                    return ReferentialEdge(pid)
            return None
        # Find current paragraph index
        idx = next((i for i, (pnum, _) in enumerate(paras)
                    if pnum == src_paragraph_num), None)
        if idx is None:
            return None
        offset = -1 if kind == "前項" else 1
        new_idx = idx + offset
        if 0 <= new_idx < len(paras):
            return ReferentialEdge(paras[new_idx][1])
        return None

    # 同号/前号/前各号/各号 — would need item-list context. Out of scope for now.
    return None
