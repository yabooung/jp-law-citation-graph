"""Publish one monthly rebuild to the Hugging Face dataset and tag it with its e-Gov snapshot date.

    python tools/publish_hf.py --release work/release --db work/jp_search.sqlite \
        --snapshot-json work/raw/_snapshot.json --as-of 20261029

Uploads (added or replaced; other files such as README.md are left alone):
    data/…                           release data files from `jlawcite export`
    eval/nta_retrieval_results.json  if present in --release
    index/jp_search.sqlite.gz        gzip of the search DB
    index/MANIFEST.json              snapshot, as_of, sha256/bytes of the DB, jlawcite version, git rev
then creates the tag YYYY-MM-DD. Exits 0 without uploading if that tag already exists
(e-Gov has not changed since the last run). Needs $HF_TOKEN (or a cached `hf auth login`).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

import jlawcite

REPO = os.environ.get("JLAWCITE_HF_REPO", "dbwjspdlagjdyd/jp-law-citation-graph")


def snapshot_date(snapshot_json: Path) -> str:
    return json.loads(snapshot_json.read_text(encoding="utf-8"))["zip_csv_timestamp"][:10]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", type=Path, required=True, help="dir with data/ from `jlawcite export`")
    ap.add_argument("--db", type=Path, required=True, help="search DB from `jlawcite index`")
    ap.add_argument("--snapshot-json", type=Path, required=True, help="_snapshot.json from `jlawcite fetch`")
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--dry-run", action="store_true", help="stage files but do not upload")
    a = ap.parse_args()

    tag = snapshot_date(a.snapshot_json)
    api = HfApi()
    if not a.dry_run and tag in {t.name for t in api.list_repo_refs(REPO, repo_type="dataset").tags}:
        print(f"[publish] tag {tag} already on {REPO}; nothing to do", file=sys.stderr)
        return 0

    stage = Path(tempfile.mkdtemp(prefix="jlawcite-publish-"))
    try:
        shutil.copytree(a.release / "data", stage / "data")
        results = a.release / "nta_retrieval_results.json"
        if results.exists():
            (stage / "eval").mkdir()
            shutil.copy2(results, stage / "eval" / results.name)
        (stage / "index").mkdir()
        h = hashlib.sha256()
        with a.db.open("rb") as src, gzip.open(stage / "index" / "jp_search.sqlite.gz", "wb", 6) as dst:
            while chunk := src.read(1 << 20):
                h.update(chunk)
                dst.write(chunk)
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             cwd=Path(__file__).resolve().parents[1]).stdout.strip()
        manifest = {
            "snapshot": tag,
            "as_of": a.as_of,
            "sha256": h.hexdigest(),
            "bytes": a.db.stat().st_size,
            "gz_bytes": (stage / "index" / "jp_search.sqlite.gz").stat().st_size,
            "jlawcite": jlawcite.__version__,
            "git_rev": rev,
        }
        (stage / "index" / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        if a.dry_run:
            print(f"[publish] dry run, staged at {stage}", file=sys.stderr)
            stage = None
            return 0
        api.upload_folder(folder_path=stage, repo_id=REPO, repo_type="dataset",
                          commit_message=f"e-Gov snapshot {tag} (as of {a.as_of})")
        api.create_tag(REPO, tag=tag, repo_type="dataset")
        print(f"[publish] {REPO} @ {tag}", file=sys.stderr)
        return 0
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
