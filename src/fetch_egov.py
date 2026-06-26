#!/usr/bin/env python3
"""Download an e-Gov law snapshot for ``build_graph.py``.

Uses the official e-Gov 法令API v2 (https://laws.e-gov.go.jp/apitop/), verified
against the live API (2026-06). Writes a snapshot directory:

    <out>/all_law_list.csv      法令ID, 法令名, 旧法令名, 法令番号, 法令種別, 本文URL
    <out>/<law_id>.xml          standard e-Gov law XML (<Law> root), parser-compatible

Then:  python build_graph.py --corpus <out> --out ../data/

NOTE on 旧法令名 (former law names): the v2 API does not expose this field, so the
column is left empty here. Renamed-law (old_name) resolution therefore only fires
when the column is populated — e.g. from the e-Gov *search-UI* CSV export
(法令検索目録), which the reference snapshot used. Everything else works as-is.

Pure standard library. Be polite: default 0.3s between requests (~9,500 laws).
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

API = "https://laws.e-gov.go.jp/api/2"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "jlaw-citegraph/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def iter_law_list(limit_total: int = 0):
    """Yield law records (dicts) from /api/2/laws, following pagination."""
    import json
    offset, seen = 0, 0
    while True:
        page = json.loads(_get(f"{API}/laws?limit=300&offset={offset}"))
        laws = page.get("laws", [])
        if not laws:
            break
        for law in laws:
            yield law
            seen += 1
            if limit_total and seen >= limit_total:
                return
        nxt = page.get("next_offset")
        if nxt is None or nxt <= offset:
            break
        offset = nxt


def fetch_law_xml(law_id: str) -> bytes | None:
    """Fetch a law and return its bare <Law> XML (parser-compatible), or None."""
    data = _get(f"{API}/law_data/{law_id}?response_format=xml")
    law = ET.fromstring(data).find(".//Law")
    return ET.tostring(law, encoding="utf-8") if law is not None else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--limit", type=int, default=0, help="cap #laws (0=all; for testing)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cols = ["法令ID", "法令名", "旧法令名", "法令番号", "法令種別", "本文URL"]
    n = 0
    with (args.out / "all_law_list.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for law in iter_law_list(args.limit):
            info = law.get("law_info", {})
            rev = law.get("current_revision_info") or law.get("revision_info", {})
            lid = info.get("law_id", "")
            if not lid:
                continue
            w.writerow([lid, rev.get("law_title", ""), "",  # 旧法令名: not in v2 API (see note)
                        info.get("law_num", ""), info.get("law_type", ""),
                        f"https://laws.e-gov.go.jp/law/{lid}"])
            xml_path = args.out / f"{lid}.xml"
            if not xml_path.exists():
                try:
                    xml = fetch_law_xml(lid)
                    if xml:
                        xml_path.write_bytes(xml)
                except Exception as e:
                    print(f"  ! {lid}: {e}", file=sys.stderr)
                time.sleep(args.sleep)
            n += 1
            if n % 500 == 0:
                print(f"  {n} laws ...", file=sys.stderr)
    print(f"[fetch] DONE: {n} laws -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
