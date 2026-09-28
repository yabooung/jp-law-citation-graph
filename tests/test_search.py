"""Search DB (jlawcite.search) on the e2e mini corpus."""
import sys

import pytest

from jlawcite.search import CitationLookupError, SearchDB, build_index, parse_citation
from jlawcite.pipeline import ingest_full
from tests.test_ingest_e2e import ACT_ID, ACT_XML, ORD_ID, ORD_XML, _write


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    base = tmp_path_factory.mktemp("raw")
    _write(base, f"{ACT_ID}_20200401_000000000000000", ACT_XML)
    _write(base, f"{ACT_ID}_20990101_508AC0000000001", ACT_XML)
    _write(base, f"{ORD_ID}_20200401_000000000000000", ORD_XML)
    parsed = tmp_path_factory.mktemp("parsed")
    argv = sys.argv
    sys.argv = ["ingest_full", "--input", str(base), "--output", str(parsed),
                "--as-of", "20260101", "--aliases", str(base / "none.json")]
    try:
        ingest_full.main()
    finally:
        sys.argv = argv
    path = tmp_path_factory.mktemp("search") / "s.sqlite"
    build_index(parsed, path, progress=False)
    return SearchDB(path)


@pytest.mark.parametrize("text, expected", [
    ("民法第七百九条", ("民法", False, "709", None, None)),
    ("所得税法施行令14条2項", ("所得税法施行令", False, "14", 2, None)),
    ("民法 709条", ("民法", False, "709", None, None)),
    ("会社法第二条第一項第十二号の二", ("会社法", False, "2", 1, "12-2")),
    ("所得税法附則第3条", ("所得税法", True, "3", None, None)),
    ("第十条の二", ("", False, "10-2", None, None)),
])
def test_parse_citation(text, expected):
    pc = parse_citation(text)
    assert (pc.law, pc.suppl, pc.article_path, pc.paragraph, pc.item_path) == expected


def test_lookup_citation_and_assembled_text(db):
    res = db.lookup("テスト法第二条")
    assert res["node"]["id"] == f"{ACT_ID}_a2"
    # Article text = paragraphs + items, in order
    assert res["text"].split("\n") == [
        "第二条", "第一条及び第三条の規定は、附則第二条の場合に準用する。",
        "  一　甲", "  一の二　乙", "  二　前号に掲げるもの"]
    assert [p["enforcement_date"] for p in res["pending"]] == ["20990101"]
    assert db.lookup("テスト法3条2項")["node"]["id"] == f"{ACT_ID}_a3_p2"
    assert db.lookup("テスト法附則第二条")["node"]["id"] == f"{ACT_ID}_asup-sp1-2"
    assert db.lookup("第一条", law_hint="テスト法施行令")["node"]["id"] == f"{ORD_ID}_a1"


def test_lookup_errors(db):
    with pytest.raises(CitationLookupError):
        db.lookup("テスト法第九十九条")
    with pytest.raises(CitationLookupError):
        db.lookup("存在しない法律第一条")


def test_keyword_search_long_and_short_terms(db):
    hits = db.search("準用する")                       # trigram FTS
    assert hits[0]["node_id"] == f"{ACT_ID}_a2_p1"
    assert "【準用する】" in hits[0]["snippet"]
    hits = db.search("乙")                             # 1-char substring fallback
    assert [h["node_id"] for h in hits] == [f"{ACT_ID}_a2_p1"]   # Items fold into their paragraph
    assert db.search("施行 政令", law="テスト法施行令")[0]["law_id"] == ORD_ID


def test_refs_aggregate_descendants(db):
    res = db.refs(f"{ACT_ID}_a3")
    sources = {e["source"] for e in res["in"]}
    assert f"{ORD_ID}_a1_p1" in sources and f"{ORD_ID}_a2_p1" in sources
    outs = {e["target"] for e in res["out"]}
    assert f"{ACT_ID}_at-1" in outs            # REFERS_TO_ATTACHMENT from 第三条第二項


def test_cli_dispatch(capsys):
    from jlawcite import cli
    assert cli.main([]) == 0 and "jlawcite build" in capsys.readouterr().out
    assert cli.main(["nope"]) == 2
