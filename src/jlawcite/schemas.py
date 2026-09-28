"""Pydantic schemas for JP legal entities.

Authoritative reference: `docs/GRAPH_SCHEMA_V2.md`.

Layout:
    1. v2.0 graph schema (GraphNode / GraphEdge / enums) — primary
    2. v1.0 legacy models (BaseJpLegalEntity / JpNode / JpEdge / JpGoldEntry)
       — kept for consumer migration; will be removed after Phase 6.

JP-specific notes:
  - article_key allows hyphen (枝番 chain like '10-2')
  - jurisdiction always 'JP' (no local tier in JP)
  - target_type uses 'law' as umbrella; law_type carries sub-classification
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .ids.normalize import (
    ARTICLE_KEY_RE,  # noqa: F401  (re-export for downstream tools)
    LAW_ID_RE,
    validate_article_key,
    validate_law_id,
)

# =============================================================================
# v2.0 — Graph schema (Phase 1 introduction)
# =============================================================================

JpNodeType = Literal[
    "Law",
    "Article",
    "Paragraph",
    "Item",
    "SupplArticle",
    "SupplParagraph",
    "Attachment",
    "Hierarchy",
]

JpEdgeRel = Literal[
    "CONTAINS",
    "CITES",
    "DELEGATES_TO",
    "REFERS_TO_ATTACHMENT",
    "SUPERSEDES",
    "AMENDS",
]

JpFallbackLevel = Literal[
    "exact",
    "paragraph_to_article",
    "law_only",
    "promulgation_only",
]

JpSection = Literal["main", "suppl"]

JpLawType = Literal[
    "act",                  # 法律 (AC)
    "cabinet_order",        # 政令 (CO)
    "ministerial_ordinance",  # 省令/府令 (M50, F0, etc.)
    "rule",                 # 規則
    "imperial_order",       # 勅令
    "treaty",               # 条約
    "constitution",         # 憲法
    "other",
]

# Node-type → required positional fields. Used by validators.
_NODE_REQUIRES_PARAGRAPH = {"Paragraph", "SupplParagraph"}
_NODE_REQUIRES_ITEM = {"Item"}
_NODE_REQUIRES_ARTICLE_PATH = {
    "Article", "Paragraph", "Item", "SupplArticle", "SupplParagraph",
}


class GraphNode(BaseModel):
    """Unified v2 node. Single shape across all 8 node types.

    See docs/GRAPH_SCHEMA_V2.md §2 for field semantics.
    """
    id: str
    type: JpNodeType
    title: str = ""
    text: str = ""
    law_id: str
    parent_id: str | None = None
    section: JpSection = "main"

    # Position
    article_path: str | None = None
    paragraph_num: int | None = None
    item_num: int | None = None
    suppl_tag: str | None = None

    # Metadata
    mst_id: str = ""
    law_title: str = ""
    enforcement_date: str | None = None
    promulgation_no: str | None = None

    # Operational
    is_active: bool = True
    jurisdiction: Literal["JP"] = "JP"
    schema_version: Literal["v2.0"] = "v2.0"

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        # Law nodes use bare law_id; everything else uses article_key form.
        if LAW_ID_RE.match(v) and "_a" not in v and "_at-" not in v and "_h" not in v:
            return v
        return validate_article_key(v)

    @field_validator("law_id")
    @classmethod
    def _validate_law_id(cls, v: str) -> str:
        return validate_law_id(v)

    def model_post_init(self, __context) -> None:
        # Type-conditional positional checks (P3 enforcement).
        if self.type in _NODE_REQUIRES_ARTICLE_PATH and not self.article_path:
            raise ValueError(f"{self.type} node requires article_path: {self.id}")
        if self.type in _NODE_REQUIRES_PARAGRAPH and self.paragraph_num is None:
            raise ValueError(f"{self.type} node requires paragraph_num: {self.id}")
        if self.type in _NODE_REQUIRES_ITEM and self.item_num is None:
            raise ValueError(f"{self.type} node requires item_num: {self.id}")
        if self.type in {"SupplArticle", "SupplParagraph"} and self.section != "suppl":
            raise ValueError(f"{self.type} must have section='suppl': {self.id}")


class GraphEdge(BaseModel):
    """Unified v2 edge."""
    source: str
    target: str
    rel: JpEdgeRel

    raw: str | None = None
    fallback_level: JpFallbackLevel = "exact"
    confidence: float = 1.0
    extracted_from: str | None = None

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be in [0,1], got {v}")
        return v


class JpGoldEntry(BaseModel):
    """NTA gold dataset entry. Matches gold_jp_v1.jsonl format.

    Stable across v1/v2 — gold data is not part of the graph schema migration.
    """
    id: str
    zeimu: str
    query: str
    answer: str = ""
    title: str = ""
    gold_articles: list[str] = Field(default_factory=list)
    external_refs: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    n_total_refs: int = 0
    n_resolved: int = 0
    n_external: int = 0
    n_unresolved: int = 0
    reasons: dict[str, int] = Field(default_factory=dict)


# =============================================================================
# v1.0 — Legacy models (deprecated; will be removed after Phase 6)
# =============================================================================

JpTargetType = Literal["law", "treaty"]
JpChunkType = Literal["article", "addendum", "attachment"]
JpAttachmentSubtype = Literal["別表", "別記", "様式", "附録", "目録", "other", None]


class HierarchyItem(BaseModel):
    """Structural position within a law (편/장/절/조). v1 legacy."""
    level: str  # '編', '章', '節', '款', '条'
    num: str    # '第1条', '第2章'
    text: str = ""


class Annex(BaseModel):
    """別表 / 様式 metadata (when chunk_type=attachment). v1 legacy."""
    annex_id: str
    title: str
    annex_type: str  # 別表 / 様式 / etc.
    link: str | None = None
    content: str = ""


class BaseJpLegalEntity(BaseModel):
    """v1 legacy. Use GraphNode for new code.

    Field semantics follow a jurisdiction-neutral legal-entity layout.
    """
    target_type: JpTargetType = "law"
    article_key: str  # PRIMARY KEY — see ids/normalize.py

    article_num: str = ""
    article_title: str = ""
    full_text: str
    hierarchy: list[HierarchyItem] = Field(default_factory=list)

    law_id: str
    mst_id: str
    law_title: str = ""
    parent_law_id: str | None = None
    annexes: list[Annex] = Field(default_factory=list)
    attachment_refs: list[str] = Field(default_factory=list)
    is_latest: bool = True
    enforcement_date: str | None = None
    promulgation_date: str | None = None
    promulgation_no: str | None = None
    department: str | None = None
    law_type: JpLawType | None = None
    title_short: str | None = None
    status: str = "ACTIVE"

    citations: list[str] = Field(default_factory=list)

    chunk_type: JpChunkType = "article"
    jurisdiction: Literal["central"] = "central"
    attachment_subtype: JpAttachmentSubtype = None
    schema_version: str = "v1.0"

    section: Literal["main", "suppl"] = "main"
    paragraph_num: int = 1
    article_path: str = ""

    text: str = ""

    @field_validator("article_key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        return validate_article_key(v)

    def model_post_init(self, __context) -> None:
        if not self.text and self.full_text:
            object.__setattr__(self, "text", self.full_text)


class Article(BaseJpLegalEntity):
    """v1 legacy. 主条文 (MainProvision Article)."""
    chunk_type: Literal["article"] = "article"
    section: Literal["main"] = "main"


class Addendum(BaseJpLegalEntity):
    """v1 legacy. 附則 (SupplProvision Article)."""
    chunk_type: Literal["addendum"] = "addendum"
    section: Literal["suppl"] = "suppl"


class Attachment(BaseJpLegalEntity):
    """v1 legacy. 別表 / 様式 / 別記."""
    chunk_type: Literal["attachment"] = "attachment"


class JpNode(BaseModel):
    """v1 legacy node format (for loaders written against v1).

    NOTE: in v1 'Article' was used for paragraph-level nodes. v2 splits Article
    and Paragraph — see GraphNode.
    """
    id: str
    title: str
    type: Literal["Law", "Article", "SupplArticle", "Attachment"]
    is_active: bool = True
    jurisdiction: str = "JP"
    law_id: str | None = None
    article_path: str | None = None
    paragraph_num: int | None = None
    section: str | None = None
    text: str | None = None


class JpEdge(BaseModel):
    """v1 legacy edge format. v2 uses GraphEdge with richer metadata."""
    source: str
    target: str
    rel: Literal["CONTAINS", "CITES", "REFERS_TO_ATTACHMENT", "DELEGATES_TO"]
