"""Tests for pipeline.validate (V01–V11 checks)."""
import pytest

from jlawcite.pipeline.validate import (
    v01_node_id_format,
    v02_contains_endpoints_in_nodes,
    v03_contains_no_cycle,
    v04_unique_parent,
    v05_cites_target_in_nodes,
    v06_enum_usage,
    v09_resolution_conservation,
    v10_no_duplicate_node_ids,
    v11_body_text_floor,
)


# ---------- V01 ----------
def test_v01_passes_on_good_ids():
    nodes = [
        {"id": "340AC0000000033", "type": "Law"},
        {"id": "340AC0000000033_a10", "type": "Article"},
        {"id": "340AC0000000033_a10_p1", "type": "Paragraph"},
    ]
    assert v01_node_id_format(nodes).passed


def test_v01_fails_on_bad_ids():
    nodes = [{"id": "garbage_xyz", "type": "Law"}]
    r = v01_node_id_format(nodes)
    assert not r.passed
    assert "garbage_xyz" in r.details


# ---------- V02 ----------
def test_v02_dangling_target():
    nodes = [{"id": "L"}, {"id": "L_a1"}]
    edges = [{"source": "L", "target": "L_a1", "rel": "CONTAINS"},
             {"source": "L_a1", "target": "L_aMissing", "rel": "CONTAINS"}]
    assert not v02_contains_endpoints_in_nodes(nodes, edges).passed


def test_v02_clean():
    nodes = [{"id": "L"}, {"id": "L_a1"}]
    edges = [{"source": "L", "target": "L_a1", "rel": "CONTAINS"}]
    assert v02_contains_endpoints_in_nodes(nodes, edges).passed


# ---------- V03 ----------
def test_v03_detects_cycle():
    nodes = [{"id": "A"}, {"id": "B"}]
    edges = [{"source": "A", "target": "B", "rel": "CONTAINS"},
             {"source": "B", "target": "A", "rel": "CONTAINS"}]
    assert not v03_contains_no_cycle(nodes, edges).passed


def test_v03_passes_dag():
    nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
    edges = [{"source": "A", "target": "B", "rel": "CONTAINS"},
             {"source": "B", "target": "C", "rel": "CONTAINS"}]
    assert v03_contains_no_cycle(nodes, edges).passed


# ---------- V04 ----------
def test_v04_multi_parent_fails():
    nodes = [{"id": "L", "type": "Law"},
             {"id": "X", "type": "Article"}]
    edges = [{"source": "L", "target": "X", "rel": "CONTAINS"},
             {"source": "L", "target": "X", "rel": "CONTAINS"}]
    assert not v04_unique_parent(nodes, edges).passed


def test_v04_orphan_fails():
    nodes = [{"id": "L", "type": "Law"},
             {"id": "X", "type": "Article"}]  # no parent edge
    assert not v04_unique_parent(nodes, []).passed


def test_v04_passes_clean():
    nodes = [{"id": "L", "type": "Law"},
             {"id": "X", "type": "Article"}]
    edges = [{"source": "L", "target": "X", "rel": "CONTAINS"}]
    assert v04_unique_parent(nodes, edges).passed


# ---------- V05 ----------
def test_v05_dangling_cites():
    nodes = [{"id": "X"}, {"id": "Y"}]
    cites = [{"source": "X", "target": "Y"},
             {"source": "X", "target": "Z"}]  # Z missing
    assert not v05_cites_target_in_nodes(nodes, cites).passed


# ---------- V06 ----------
def test_v06_warns_on_missing_enum():
    nodes = [{"type": "Law"}, {"type": "Article"}]
    edges = [{"rel": "CONTAINS"}]
    r = v06_enum_usage(nodes, edges)
    # Many missing types/rels → check fails (WARN severity)
    assert not r.passed
    assert "missing" in r.details


def test_v06_passes_when_all_enums_present():
    nodes = [{"type": t} for t in
             ("Law", "Article", "Paragraph", "Item",
              "SupplArticle", "SupplParagraph", "Hierarchy", "Attachment")]
    edges = [{"rel": r} for r in
             ("CONTAINS", "CITES", "DELEGATES_TO",
              "REFERS_TO_ATTACHMENT", "AMENDS")]
    assert v06_enum_usage(nodes, edges).passed


# ---------- V09 ----------
def test_v09_negative_count_fails():
    assert not v09_resolution_conservation({"foo": -1}).passed


def test_v09_clean():
    assert v09_resolution_conservation({"foo": 10, "bar": 0}).passed


# ---------- V10 ----------
def test_v10_unique_ids_pass():
    nodes = [{"id": "L"}, {"id": "L_a1"}, {"id": "L_a1_p1"}]
    assert v10_no_duplicate_node_ids(nodes).passed


def test_v10_duplicate_ids_fail():
    nodes = [{"id": "L"}, {"id": "L_a1"}, {"id": "L_a1"}]
    r = v10_no_duplicate_node_ids(nodes)
    assert not r.passed
    assert "L_a1" in r.details


# ---------- V11 ----------
def _para(i: int, text: str) -> dict:
    return {"id": f"L_a1_p{i}", "type": "Paragraph", "text": text}


def test_v11_passes_on_healthy_paragraphs():
    # 100 paragraphs, all with substantive body text
    nodes = [_para(i, "本文" * 30) for i in range(1, 101)]
    nodes.append({"id": "L", "type": "Law", "text": ""})  # Law excluded — empty OK
    nodes.append({"id": "L_a1", "type": "Article", "text": ""})  # Article excluded
    assert v11_body_text_floor(nodes).passed


def test_v11_fails_on_kr_style_header_only_regression():
    # Simulate KR bug — nearly all body text dropped, only headers present.
    # 100 paragraphs but 95 are empty (95% empty > 1% threshold)
    nodes = [_para(i, "") for i in range(1, 96)]
    nodes += [_para(i, "本文" * 30) for i in range(96, 101)]
    r = v11_body_text_floor(nodes)
    assert not r.passed
    assert "Paragraph empty" in r.details


def test_v11_fails_on_short_p50():
    # 100 paragraphs all populated but with text below the p50 floor (30 chars)
    nodes = [_para(i, "短い") for i in range(1, 101)]
    r = v11_body_text_floor(nodes)
    assert not r.passed
    assert "len_p50" in r.details


def test_v11_ignores_excluded_types():
    # Article/SupplArticle/Law/Hierarchy/Attachment empty → ignored by V11
    nodes = [
        {"id": "L", "type": "Law", "text": ""},
        {"id": "L_a1", "type": "Article", "text": ""},
        {"id": "L_asup-X-1", "type": "SupplArticle", "text": ""},
        {"id": "L_hP1", "type": "Hierarchy", "text": ""},
        {"id": "L_at-1", "type": "Attachment", "text": ""},
    ]
    # No body-bearing nodes at all → all body-floor types have total=0 → passes vacuously
    assert v11_body_text_floor(nodes).passed
