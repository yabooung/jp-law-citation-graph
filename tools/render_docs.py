"""Fill the numbers in the docs from the files they describe, so the docs always match data/.

Each generated value in a doc is marked `<!--v:KEY-->value<!--/v-->` (the comments do not render).
CITATION.cff and the BibTeX block, where a comment cannot go, are matched by pattern instead.
The monthly refresh runs this after it updates data/; tests run it with --check.

    python tools/render_docs.py          # rewrite the docs in place
    python tools/render_docs.py --check  # exit 1 if a doc is out of date

Keys come from data/release_stats.json, data/laws.csv, data/cites_law_to_law.csv,
eval/v2/nta_retrieval_results.json and pyproject.toml (see `values`); the .jsonl.gz edge files are
on Hugging Face only and are not needed.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "README.ja.md", "README.ko.md", "DATA_CARD.md", "DATA_LICENSE.md",
        "docs/METHODOLOGY.md", "CITATION.cff", "tools/hf_card_header.md"]
MARK = re.compile(r"<!--v:([^>]+?)-->(.*?)<!--/v-->", re.S)
# (file, pattern whose group 1 is the value, key) for places a marker cannot go
PATTERNS = [
    ("CITATION.cff", r"Snapshot: e-Gov (\d{4}-\d{2}-\d{2})", "snapshot"),
    ("CITATION.cff", r"([\d,]+) laws at article", "laws"),
    ("CITATION.cff", r"\(([\d.]+M) nodes", "nodes_m"),
    ("CITATION.cff", r"([\d.]+M) resolved citation edges", "cites_m"),
    ("CITATION.cff", r"([\d,]+) distinct\s+law-to-law", "pairs"),
    ("README.md", r"note    = \{e-Gov (\d{4}-\d{2}-\d{2}) snapshot\}", "snapshot"),
    ("README.md", r"  version = \{([\d.]+)\}", "version"),
    ("README.md", r"badge/release-v([\d.]+)-informative", "version"),
    ("README.ja.md", r"badge/release-v([\d.]+)-informative", "version"),
    ("README.ko.md", r"badge/release-v([\d.]+)-informative", "version"),
]


def _n(x: int) -> str:
    return f"{x:,}"


def _f(x: float, places: int) -> str:
    """Round half up on the decimal digits as written in the JSON (0.4975 → 0.498, as in the docs)."""
    return str(Decimal(repr(x)).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP))


def values(root: Path = ROOT) -> dict[str, str]:
    st = json.loads((root / "data/release_stats.json").read_text(encoding="utf-8"))
    ret = json.loads((root / "eval/v2/nta_retrieval_results.json").read_text(encoding="utf-8"))
    with (root / "data/laws.csv").open(encoding="utf-8") as f:
        laws = list(csv.DictReader(f))
    with (root / "data/cites_law_to_law.csv").open(encoding="utf-8") as f:
        cited_by = Counter(r["tgt_law"] for r in csv.DictReader(f))
    version = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M)[1]

    a = st["as_of"]
    v = {
        "version": version,
        "snapshot": st["egov_snapshot"],
        "as_of": f"{a[:4]}-{a[4:6]}-{a[6:]}",
        "laws": _n(st["laws"]),
        "law_versions": _n(st["egov_law_versions"]),
        "pending": _n(st["pending_versions"]),
        "pending_laws": _n(sum(1 for r in laws if int(r["pending_versions"] or 0) > 0)),
        "ext_edges": _n(st["external_edges"]),
        "ext_cross": _n(st["external_cross_law_edges"]),
        "ext_self": _n(st["external_self_edges"]),
        "pairs": _n(st["law_to_law_pairs"]),
        "article_links": _n(st["article_links"]),
        "pre_amendment_edges": _n(st["pre_amendment_edges"]),
        "queries": _n(ret["evaluated"]),
        "gold_records": _n(ret["gold"]["records"]),
    }
    v |= {f"type:{t}": _n(c) for t, c in Counter(r["type"] for r in laws).items()}
    v |= {f"cited_by:{name}": _n(c) for name, c in cited_by.items()}

    nodes = st["nodes"]
    total = sum(nodes.values())
    v |= {f"nodes.{k}": _n(c) for k, c in nodes.items()}
    v |= {"nodes_m": f"{total / 1e6:.2f}M", "nodes_man": f"{round(total / 1e4)}万", "nodes_man_ko": f"{round(total / 1e4)}만",
          "contains": _n(total - nodes["laws"])}   # CONTAINS is a tree over every node but the laws

    rel = st["edges_by_rel"]
    v |= {"cites": _n(rel["CITES"]), "cites_m": f"{rel['CITES'] / 1e6:.2f}M",
          "cites_man": f"{round(rel['CITES'] / 1e4)}万", "cites_man_ko": f"{round(rel['CITES'] / 1e4)}만",
          "delegates": _n(rel["DELEGATES_TO"]),
          "attachment_refs": _n(rel["REFERS_TO_ATTACHMENT"]), "amends": _n(rel["AMENDS"]),
          "all_edges": _n(sum(rel.values()))}
    for k, (ok, n) in st["resolution"].items():
        v |= {f"res.{k}": f"{ok / n * 100:.1f}%", f"res.{k}.k": _n(ok), f"res.{k}.n": _n(n)}
    v |= {f"excl.{k}": _n(c) for k, c in st["resolution_excluded"].items()}

    for m, r in ret["methods"].items():
        v |= {f"ret.{m}.{k}": _f(x, 3) for k, x in r.items() if k.startswith(("recall@", "mrr@"))}
        v |= {f"ret.{m}.s": _f(r["sec_per_query"], 2), f"ret.{m}.r10": _f(r["recall@10"], 2)}
    return v


def render(name: str, text: str, v: dict[str, str]) -> str:
    def mark(m: re.Match) -> str:
        if m[1] not in v:
            raise KeyError(f"{name}: unknown key {m[1]!r}")
        return f"<!--v:{m[1]}-->{v[m[1]]}<!--/v-->"

    text = MARK.sub(mark, text)
    for doc, pat, key in PATTERNS:
        if doc != name:
            continue
        if not re.search(pat, text):
            raise ValueError(f"{name}: pattern for {key!r} not found: {pat}")
        text = re.sub(pat, lambda m: m[0][:m.start(1) - m.start(0)] + v[key] + m[0][m.end(1) - m.start(0):], text)
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only report docs that are out of date")
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    v = values(a.root)
    stale = []
    for name in DOCS:
        p = a.root / name
        old = p.read_bytes().decode("utf-8")   # bytes: keep the file's line endings
        new = render(name, old, v)
        if new != old:
            stale.append(name)
            if not a.check:
                p.write_bytes(new.encode("utf-8"))
    if stale:
        print(("out of date: " if a.check else "updated: ") + ", ".join(stale), file=sys.stderr)
    return 1 if a.check and stale else 0


def hf_card(root: Path = ROOT) -> str:
    """Hugging Face dataset card: tools/hf_card_header.md (YAML configs + note) + DATA_CARD.md, as
    rendered in the working tree, with the markers removed and repo-relative links made absolute."""
    text = ((root / "tools/hf_card_header.md").read_text(encoding="utf-8") + "\n"
            + (root / "DATA_CARD.md").read_text(encoding="utf-8"))
    text = MARK.sub(lambda m: m[2], text)
    return re.sub(r"\]\((?!https?://|#)([^)]+)\)", r"](https://github.com/yabooung/jp-law-citation-graph/blob/main/\1)", text)


if __name__ == "__main__":
    sys.exit(main())
