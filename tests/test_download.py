"""download: fetch the search DB from a Hub-shaped tree (served over file://), pack/unpack."""
import gzip
import hashlib
import json
import lzma
import sys

import pytest

from jlawcite import search
from jlawcite.pipeline import download, ingest_full
from tests.test_ingest_e2e import ACT_ID, ACT_XML, ORD_ID, ORD_XML, _write

REPO = "someone/jp-law-citation-graph"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("raw")
    _write(base, f"{ACT_ID}_20200401_000000000000000", ACT_XML)
    _write(base, f"{ORD_ID}_20200401_000000000000000", ORD_XML)
    parsed = tmp_path_factory.mktemp("parsed")
    argv = sys.argv
    sys.argv = ["ingest_full", "--input", str(base), "--output", str(parsed),
                "--as-of", "20260101", "--aliases", str(base / "none.json")]
    try:
        ingest_full.main()
    finally:
        sys.argv = argv
    full = tmp_path_factory.mktemp("db") / "full.sqlite"
    search.build_index(parsed, full, progress=False)
    packed = full.with_name("packed.sqlite")
    search.pack(full, packed)
    return full, packed


def _chunks(db):
    import sqlite3
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT node_id, law_id, article_id, section, heading, body "
                           "FROM chunks ORDER BY rowid").fetchall()
    finally:
        con.close()


def _publish(root, rev, db, name):
    idx = root / "datasets" / REPO / "resolve" / rev / "index"
    idx.mkdir(parents=True)
    raw = db.read_bytes()
    (idx / name).write_bytes(lzma.compress(raw) if name.endswith(".xz") else gzip.compress(raw))
    (idx / "MANIFEST.json").write_text(json.dumps({
        "snapshot": rev if rev != "main" else "2026-10-27", "as_of": "20261029", "file": name,
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}))
    data = idx.parent / "data"
    data.mkdir()
    for f in download.DATA_FILES:
        (data / f).write_text(f)


@pytest.fixture
def hub(built, tmp_path, monkeypatch):
    full, packed = built
    _publish(tmp_path, "main", packed, "jp_search.sqlite.xz")
    _publish(tmp_path, "2026-09-27", full, "jp_search.sqlite.gz")   # older, unpacked layout
    api = tmp_path / "api" / "datasets" / REPO
    api.mkdir(parents=True)
    (api / "refs").write_text(json.dumps({"branches": [{"name": "main"}],
                                          "tags": [{"name": "2026-09-27"}, {"name": "2026-10-27"}]}))
    monkeypatch.setenv("JLAWCITE_HF_ENDPOINT", tmp_path.as_uri())
    monkeypatch.setenv("JLAWCITE_HF_REPO", REPO)
    return full


def test_pack_drops_chunks_and_unpack_restores_them(built, tmp_path):
    full, packed = built
    assert search.is_packed(packed) and not search.is_packed(full)
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(packed.read_bytes())
    search.unpack(copy, progress=False)
    assert not search.is_packed(copy)
    assert _chunks(copy) == _chunks(full)
    hits = search.SearchDB(copy).search("法律", limit=5)
    assert [h["node_id"] for h in hits] == [h["node_id"] for h in search.SearchDB(full).search("法律", limit=5)]


def test_download_unpacks_and_skips_when_current(hub, tmp_path, capsys):
    db = tmp_path / "out" / "jp_search.sqlite"
    m = download.download_db("main", db)
    assert m["snapshot"] == "2026-10-27"
    assert not search.is_packed(db) and _chunks(db) == _chunks(hub)
    assert all((db.parent / f).exists() for f in download.LAW_FILES)
    assert json.loads((db.parent / "jp_search.sqlite.json").read_text())["revision"] == "main"
    download.download_db("main", db)
    assert "up to date" in capsys.readouterr().err


def test_download_rejects_bad_checksum(hub, tmp_path):
    man = tmp_path / "datasets" / REPO / "resolve" / "main" / "index" / "MANIFEST.json"
    man.write_text(json.dumps({**json.loads(man.read_text()), "sha256": "0" * 64}))
    db = tmp_path / "out" / "jp_search.sqlite"
    with pytest.raises(RuntimeError, match="sha256"):
        download.download_db("main", db)
    assert not db.exists()


def test_old_gz_snapshot_data_and_list(hub, tmp_path):
    out = tmp_path / "data_out"
    db = tmp_path / "s.sqlite"
    assert download.main(["--snapshot", "2026-09-27", "--db", str(db), "--data", str(out)]) == 0
    assert db.read_bytes() == hub.read_bytes()
    assert sorted(p.name for p in out.iterdir()) == sorted(download.DATA_FILES)
    assert download.list_snapshots() == ["2026-10-27", "2026-09-27"]
