"""Tests for jlawcite.schemas v2.0 graph models."""
import pytest
from pydantic import ValidationError

from jlawcite.schemas import GraphEdge, GraphNode


# ---------- GraphNode happy paths ----------
def test_law_node():
    n = GraphNode(id="340AC0000000033", type="Law", title="所得税法",
                  law_id="340AC0000000033")
    assert n.schema_version == "v2.0"
    assert n.jurisdiction == "JP"


def test_article_node():
    n = GraphNode(
        id="340AC0000000033_a10",
        type="Article",
        law_id="340AC0000000033",
        article_path="10",
    )
    assert n.paragraph_num is None
    assert n.item_num is None


def test_paragraph_node():
    n = GraphNode(
        id="340AC0000000033_a10_p1",
        type="Paragraph",
        law_id="340AC0000000033",
        article_path="10",
        paragraph_num=1,
        text="...",
    )
    assert n.text == "..."


def test_item_node():
    n = GraphNode(
        id="340AC0000000033_a10_p1_i2",
        type="Item",
        law_id="340AC0000000033",
        article_path="10",
        paragraph_num=1,
        item_num=2,
    )
    assert n.item_num == 2


def test_suppl_paragraph_node():
    n = GraphNode(
        id="340AC0000000033_asup-X-5_p1",
        type="SupplParagraph",
        law_id="340AC0000000033",
        article_path="5",
        paragraph_num=1,
        section="suppl",
        suppl_tag="X",
    )
    assert n.section == "suppl"


def test_attachment_node():
    n = GraphNode(
        id="340AC0000000033_at-1",
        type="Attachment",
        law_id="340AC0000000033",
        title="別表第1",
    )
    assert n.type == "Attachment"


def test_hierarchy_node():
    n = GraphNode(
        id="340AC0000000033_hP1C2",
        type="Hierarchy",
        law_id="340AC0000000033",
        title="第2章",
    )
    assert n.type == "Hierarchy"


# ---------- GraphNode validation failures ----------
def test_paragraph_requires_paragraph_num():
    with pytest.raises(ValidationError):
        GraphNode(
            id="340AC0000000033_a10_p1",
            type="Paragraph",
            law_id="340AC0000000033",
            article_path="10",
            # paragraph_num missing
        )


def test_item_requires_item_num():
    with pytest.raises(ValidationError):
        GraphNode(
            id="340AC0000000033_a10_p1_i1",
            type="Item",
            law_id="340AC0000000033",
            article_path="10",
            paragraph_num=1,
            # item_num missing
        )


def test_article_requires_article_path():
    with pytest.raises(ValidationError):
        GraphNode(
            id="340AC0000000033_a10",
            type="Article",
            law_id="340AC0000000033",
            # article_path missing
        )


def test_suppl_must_have_suppl_section():
    with pytest.raises(ValidationError):
        GraphNode(
            id="340AC0000000033_asup-X-5",
            type="SupplArticle",
            law_id="340AC0000000033",
            article_path="5",
            section="main",  # wrong
            suppl_tag="X",
        )


def test_invalid_id_format():
    with pytest.raises(ValidationError):
        GraphNode(
            id="not_a_valid_key",
            type="Article",
            law_id="340AC0000000033",
            article_path="10",
        )


def test_invalid_law_id():
    with pytest.raises(ValidationError):
        GraphNode(
            id="340AC0000000033",
            type="Law",
            law_id="bad",
        )


# ---------- GraphEdge ----------
def test_edge_minimal():
    e = GraphEdge(
        source="340AC0000000033",
        target="340AC0000000033_a1_p1",
        rel="CONTAINS",
    )
    assert e.fallback_level == "exact"
    assert e.confidence == 1.0


def test_edge_with_metadata():
    e = GraphEdge(
        source="340AC0000000033_a10_p1",
        target="340AC0000000033_a5",
        rel="CITES",
        raw="第5条",
        fallback_level="paragraph_to_article",
        confidence=0.9,
        extracted_from="INTERNAL_PAT",
    )
    assert e.fallback_level == "paragraph_to_article"
    assert e.confidence == 0.9


def test_edge_confidence_bounds():
    with pytest.raises(ValidationError):
        GraphEdge(
            source="x", target="y", rel="CITES", confidence=1.5,
        )
    with pytest.raises(ValidationError):
        GraphEdge(
            source="x", target="y", rel="CITES", confidence=-0.1,
        )


def test_edge_rel_enum():
    # All 6 rels accepted
    for rel in ("CONTAINS", "CITES", "DELEGATES_TO",
                "REFERS_TO_ATTACHMENT", "SUPERSEDES", "AMENDS"):
        GraphEdge(source="x", target="y", rel=rel)
    with pytest.raises(ValidationError):
        GraphEdge(source="x", target="y", rel="UNKNOWN_REL")
