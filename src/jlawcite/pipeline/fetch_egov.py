"""Fetch the e-Gov 法令 XML bulk dump into `data/raw/law_xml`.

Downloads `all_xml.zip` from the e-Gov 一括ダウンロード endpoint and extracts it
into the layout `ingest_full` expects:

    data/raw/law_xml/
        all_law_list.csv
        {law_id}_{YYYYMMDD}_{amend_id}/{law_id}_{YYYYMMDD}_{amend_id}.xml
        _snapshot.json      # fetch metadata (written by this script)

Extraction goes into a sibling temp dir first and is swapped in only on
success, so a failed download never leaves a half-populated raw dir. The
previous snapshot is kept as `law_xml.prev/` unless `--no-backup`.

Usage:
    jlawcite fetch --output data/raw/law_xml
    jlawcite fetch --output data/raw/law_xml --zip path/to/all_xml.zip
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from tqdm import tqdm

BULK_URL = "https://laws.e-gov.go.jp/bulkdownload?file_section=1&only_xml_flag=true"
CSV_NAME = "all_law_list.csv"
SNAPSHOT_NAME = "_snapshot.json"


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "jlawcite/fetch_egov"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as f:
        total = int(resp.headers.get("Content-Length") or 0) or None
        with tqdm(total=total, unit="B", unit_scale=True, desc="Download") as bar:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
                bar.update(len(chunk))


def extract(zip_fp: Path, out_dir: Path) -> dict:
    """Extract zip into out_dir and return snapshot stats. Raises on bad layout."""
    with zipfile.ZipFile(zip_fp) as z:
        names = z.namelist()
        if CSV_NAME not in names:
            raise ValueError(f"{CSV_NAME} not found at zip root — layout changed?")
        xmls = [n for n in names if n.endswith(".xml")]
        if not xmls:
            raise ValueError("no XML files in zip")
        for n in tqdm(names, desc="Extract"):
            z.extract(n, out_dir)
        csv_date = dt.datetime(*z.getinfo(CSV_NAME).date_time).isoformat()

    with (out_dir / CSV_NAME).open(encoding="utf-8-sig") as f:
        csv_rows = sum(1 for _ in f) - 1
    law_ids = {Path(n).name.split("_")[0] for n in xmls}
    return {
        "source_url": BULK_URL,
        "fetched_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "zip_csv_timestamp": csv_date,
        "zip_bytes": zip_fp.stat().st_size,
        "xml_versions": len(xmls),
        "unique_law_ids": len(law_ids),
        "csv_rows": csv_rows,
    }


def main():
    ap = argparse.ArgumentParser(description="Fetch e-Gov 法令 XML bulk dump")
    ap.add_argument("--output", type=Path, default=Path("data/raw/law_xml"),
                    help="Target raw XML dir (default: data/raw/law_xml)")
    ap.add_argument("--zip", type=Path, default=None,
                    help="Use an already-downloaded all_xml.zip instead of fetching")
    ap.add_argument("--keep-zip", type=Path, default=None,
                    help="Save the downloaded zip to this path")
    ap.add_argument("--no-backup", action="store_true",
                    help="Delete the previous snapshot instead of keeping it as <output>.prev")
    args = ap.parse_args()

    out: Path = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{out.name}.", suffix=".tmp", dir=out.parent))

    try:
        if args.zip:
            zip_fp = args.zip
        else:
            zip_fp = args.keep_zip or staging.with_suffix(".zip")
            print(f"[fetch] {BULK_URL}", file=sys.stderr)
            download(BULK_URL, zip_fp)

        stats = extract(zip_fp, staging)
        (staging / SNAPSHOT_NAME).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

        if out.exists():
            prev = out.with_name(out.name + ".prev")
            if prev.exists():
                shutil.rmtree(prev)
            if args.no_backup:
                shutil.rmtree(out)
            else:
                out.rename(prev)
                print(f"[fetch] Previous snapshot kept at {prev}", file=sys.stderr)
        staging.rename(out)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        tmp_zip = staging.with_suffix(".zip")
        if not args.zip and not args.keep_zip and tmp_zip.exists():
            tmp_zip.unlink()

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
