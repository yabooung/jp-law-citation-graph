"""Download a prebuilt search DB (and release data) from the Hugging Face dataset.

The dataset is rebuilt from e-Gov every month; each rebuild is tagged with its
e-Gov snapshot date (YYYY-MM-DD), and `main` is the latest.

    <prog> download                          latest snapshot → ~/.cache/jlawcite/
    <prog> download --snapshot 2026-09-27    a fixed snapshot (for reproducible experiments)
    <prog> download --list                   available snapshots
    <prog> download --data DIR               also all release data files (edges …)

The DB is shipped packed (no chunk table / FTS index, xz, ~115 MB) and unpacked
locally (~1 min, ~2.6 GB). laws.csv, cites_law_to_law.csv and pending_versions.csv (used by `jlawcite mcp`)
are always saved next to the DB.

Layout on the Hub (written by the monthly refresh):
    index/jp_search.sqlite.xz   packed search DB (older snapshots: jp_search.sqlite.gz, unpacked)
    index/MANIFEST.json         {"snapshot", "as_of", "file", "sha256", "bytes", …}
                                sha256/bytes are of the DB as shipped (before unpack)
    data/…                      release data files (see export_release)

Environment: $JLAWCITE_HF_REPO (default dbwjspdlagjdyd/jp-law-citation-graph),
$JLAWCITE_HF_ENDPOINT (default https://huggingface.co), $JLAWCITE_HOME (cache dir).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import lzma
import os
import sys
import urllib.request
from pathlib import Path

from tqdm import tqdm

from jlawcite import search as search_lib
from jlawcite.pipeline.search_cli import CACHE_DB

DEFAULT_REPO = "dbwjspdlagjdyd/jp-law-citation-graph"
DATA_FILES = ["laws.csv", "cites_edges.jsonl.gz", "cites_law_to_law.csv",
              "cites_all_edges.jsonl.gz", "pending_versions.csv", "release_stats.json"]
LAW_FILES = ["laws.csv", "cites_law_to_law.csv", "pending_versions.csv"]  # saved next to the DB
_UA = {"User-Agent": "jlawcite/download"}


def _endpoint() -> str:
    return os.environ.get("JLAWCITE_HF_ENDPOINT", "https://huggingface.co").rstrip("/")


def _repo() -> str:
    return os.environ.get("JLAWCITE_HF_REPO", DEFAULT_REPO)


def file_url(path: str, revision: str) -> str:
    return f"{_endpoint()}/datasets/{_repo()}/resolve/{revision}/{path}"


def _open(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=120)


def list_snapshots() -> list[str]:
    with _open(f"{_endpoint()}/api/datasets/{_repo()}/refs") as r:
        refs = json.load(r)
    return sorted((t["name"] for t in refs.get("tags", [])), reverse=True)


def fetch_manifest(revision: str) -> dict:
    with _open(file_url("index/MANIFEST.json", revision)) as r:
        return json.load(r)


def _stream(url: str, dest: Path, *, desc: str) -> str:
    """Download url into dest (via a temp file), decompressing .gz / .xz by the URL's
    suffix; return the sha256 of what was written."""
    tmp = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    with _open(url) as resp:
        total = int(resp.headers.get("Content-Length") or 0) or None
        with tqdm(total=total, unit="B", unit_scale=True, desc=desc) as bar:
            class _Counted:
                def read(self, n=-1):
                    b = resp.read(n)
                    bar.update(len(b))
                    return b
            if url.endswith(".xz"):
                src = lzma.LZMAFile(_Counted())
            elif url.endswith(".sqlite.gz"):
                src = gzip.GzipFile(fileobj=_Counted())
            else:
                src = _Counted()
            with tmp.open("wb") as f:
                while chunk := src.read(1 << 20):
                    h.update(chunk)
                    f.write(chunk)
    tmp.replace(dest)
    return h.hexdigest()


def download_db(revision: str, db: Path, *, force: bool = False) -> dict:
    manifest = fetch_manifest(revision)
    meta_fp = db.with_name(db.name + ".json")
    if not force and db.exists() and meta_fp.exists():
        have = json.loads(meta_fp.read_text(encoding="utf-8"))
        if have.get("sha256") == manifest["sha256"]:
            print(f"[download] up to date: snapshot {manifest['snapshot']} at {db}", file=sys.stderr)
            return manifest
    db.parent.mkdir(parents=True, exist_ok=True)
    for f in LAW_FILES:   # small; first, so graph-only tools work while the DB unpacks
        _stream(file_url(f"data/{f}", revision), db.parent / f, desc=f)
    name = manifest.get("file", "jp_search.sqlite.gz")
    sha = _stream(file_url(f"index/{name}", revision), db, desc=f"jp_search {manifest['snapshot']}")
    if sha != manifest["sha256"]:
        db.unlink()
        raise RuntimeError(f"sha256 mismatch: got {sha}, manifest {manifest['sha256']}")
    if search_lib.is_packed(db):
        search_lib.unpack(db)
    meta_fp.write_text(json.dumps({**manifest, "revision": revision}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return manifest


def download_data(revision: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in DATA_FILES:
        _stream(file_url(f"data/{name}", revision), out / name, desc=name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jlawcite download",
                                 description="Download the prebuilt search DB from Hugging Face")
    ap.add_argument("--snapshot", default="main",
                    help="e-Gov snapshot tag (YYYY-MM-DD); default: latest")
    ap.add_argument("--db", type=Path, default=CACHE_DB, help=f"where to put the DB (default: {CACHE_DB})")
    ap.add_argument("--data", type=Path, help="also download all release data files into this dir")
    ap.add_argument("--list", action="store_true", help="list available snapshots and exit")
    ap.add_argument("--force", action="store_true", help="re-download even if up to date")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if a.list:
        for tag in list_snapshots():
            print(tag)
        return 0
    manifest = download_db(a.snapshot, a.db, force=a.force)
    if a.data:
        download_data(a.snapshot, a.data)
    print(json.dumps({**manifest, "db": str(a.db)}, ensure_ascii=False, indent=2))
    if a.db != CACHE_DB and not os.environ.get("JLAWCITE_DB"):
        print(f"[download] set JLAWCITE_DB={a.db} or pass --db to use it", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
