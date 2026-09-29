"""download: fetch the gzipped search DB from a Hub-shaped tree (served over file://)."""
import gzip
import hashlib
import json

import pytest

from jlawcite.pipeline import download

REPO = "someone/jp-law-citation-graph"


@pytest.fixture
def hub(tmp_path, monkeypatch):
    payload = b"SQLite format 3\x00" + bytes(range(256)) * 64
    for rev in ("main", "2026-09-27"):
        idx = tmp_path / "datasets" / REPO / "resolve" / rev / "index"
        idx.mkdir(parents=True)
        (idx / "jp_search.sqlite.gz").write_bytes(gzip.compress(payload))
        (idx / "MANIFEST.json").write_text(json.dumps({
            "snapshot": "2026-09-27", "as_of": "20260929",
            "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}))
        data = idx.parent / "data"
        data.mkdir()
        for name in download.DATA_FILES:
            (data / name).write_text(name)
    api = tmp_path / "api" / "datasets" / REPO
    api.mkdir(parents=True)
    (api / "refs").write_text(json.dumps({"branches": [{"name": "main"}],
                                          "tags": [{"name": "2026-09-27"}, {"name": "2026-10-27"}]}))
    monkeypatch.setenv("JLAWCITE_HF_ENDPOINT", tmp_path.as_uri())
    monkeypatch.setenv("JLAWCITE_HF_REPO", REPO)
    return payload


def test_download_db_verifies_and_skips_when_current(hub, tmp_path, capsys):
    db = tmp_path / "out" / "jp_search.sqlite"
    m = download.download_db("main", db)
    assert db.read_bytes() == hub
    assert m["snapshot"] == "2026-09-27"
    assert json.loads((db.parent / "jp_search.sqlite.json").read_text())["revision"] == "main"
    download.download_db("main", db)
    assert "up to date" in capsys.readouterr().err


def test_download_db_rejects_bad_checksum(hub, tmp_path):
    man = tmp_path / "datasets" / REPO / "resolve" / "main" / "index" / "MANIFEST.json"
    man.write_text(json.dumps({**json.loads(man.read_text()), "sha256": "0" * 64}))
    db = tmp_path / "out" / "jp_search.sqlite"
    with pytest.raises(RuntimeError, match="sha256"):
        download.download_db("main", db)
    assert not db.exists()


def test_snapshot_tag_data_and_list(hub, tmp_path):
    out = tmp_path / "data_out"
    assert download.main(["--snapshot", "2026-09-27", "--db", str(tmp_path / "s.sqlite"),
                          "--data", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == sorted(download.DATA_FILES)
    assert download.list_snapshots() == ["2026-10-27", "2026-09-27"]
