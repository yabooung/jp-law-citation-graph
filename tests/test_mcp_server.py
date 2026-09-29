"""mcp_server tools on a mini data dir + the e2e search DB (the `mcp` package is not needed)."""
import pytest

from jlawcite.pipeline import mcp_server
from tests.test_download import built  # noqa: F401 — module-scoped DB fixture
from tests.test_ingest_e2e import ACT_ID, ORD_ID


@pytest.fixture
def data(built, tmp_path, monkeypatch):  # noqa: F811
    full, _packed = built
    (tmp_path / "laws.csv").write_text(
        "law_id,name,type,url,enforcement_date,next_enforcement_date,pending_versions\n"
        f"{ACT_ID},テスト法,法律,https://example/{ACT_ID},20200401,,0\n"
        f"{ORD_ID},テスト法施行令,政令,https://example/{ORD_ID},20200401,,0\n", encoding="utf-8")
    (tmp_path / "cites_law_to_law.csv").write_text(
        "src_law_id,src_law,tgt_law_id,tgt_law,n_citations\n"
        f"{ORD_ID},テスト法施行令,{ACT_ID},テスト法,3\n", encoding="utf-8")
    (tmp_path / "pending_versions.csv").write_text(
        "law_id,law_title,enforcement_date\n" f"{ACT_ID},テスト法,20990101\n", encoding="utf-8")
    monkeypatch.setenv("JLAWCITE_DATA", str(tmp_path))
    monkeypatch.setenv("JLAWCITE_DB", str(full))
    monkeypatch.setattr(mcp_server, "_graph", None)
    return tmp_path


def test_graph_tools(data):
    assert mcp_server.get_law("テスト法")["cited_by_count"] == 1
    assert mcp_server.what_cites("テスト法")["cited_by"][0]["law"] == "テスト法施行令"
    assert mcp_server.what_law_cites(ORD_ID)["cites"][0]["weight"] == 3
    assert mcp_server.citation_path("テスト法施行令", "テスト法")["hops"] == 1
    assert mcp_server.pending_amendments("テスト法")["pending"][0]["enforcement_date"] == "20990101"
    assert mcp_server.get_law("存在しない法")["error"].startswith("law not found")
    hits = mcp_server.resolve_citation("テスト法第一条の規定による")
    assert hits and hits[0]["law_id"] == ACT_ID


def test_db_tools(data):
    p = mcp_server.get_provision("テスト法第一条")
    assert p["law"] == "テスト法" and p["text"]
    assert "hits" in mcp_server.search_statutes("規定")


def test_missing_data_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("JLAWCITE_DATA", str(tmp_path))
    monkeypatch.setenv("JLAWCITE_DB", str(tmp_path / "none.sqlite"))
    monkeypatch.setattr(mcp_server, "_graph", None)
    assert "error" in mcp_server._safe(mcp_server.get_law)("テスト法")
    assert "jlawcite download" in mcp_server._safe(mcp_server.get_provision)("テスト法第一条")["error"]
