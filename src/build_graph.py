#!/usr/bin/env python3
"""Build the Japanese statutory citation graph from an e-Gov law snapshot.

Deterministic end-to-end pipeline:
    e-Gov XML  ->  parse (条/項/号)  ->  extract citations  ->  resolve  ->  export

Usage:
    python build_graph.py --corpus <dir> --out <dir>

  <dir> must contain e-Gov law XML files (either ``*/*.xml`` or flat ``*.xml``)
  and ``all_law_list.csv`` (the e-Gov law list, with 法令ID/法令名/旧法令名/
  法令番号/法令種別/本文URL columns).  Use ``fetch_egov.py`` to download one.

Outputs (in --out):
    laws.csv               nodes: law_id, name, type, url
    cites_law_to_law.csv   aggregated edges: src/tgt + n_citations
    cites_edges.jsonl.gz   full edges: src/tgt law+article, via, confidence

No randomness: the same snapshot + code produce a byte-identical graph.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

from jlawcite import citation, resolver, parser as xmlp

# Anaphora tokens whose referent is defined locally (in-law 附則 definitions).
ANAPHORA_TOKENS = ("新法", "旧法", "新令", "旧令", "新規則", "旧規則")
_AMEND_CUT = re.compile(r"改正(?:後|前)の")
_LAWNAME_TAIL = re.compile(r"([一-鿿々ヶ、]{2,40}?(?:法律|施行令|施行規則|法|令|規則|条例|条約))$")


def load_law_list(csv_path: Path):
    """Read all_law_list.csv into the maps the resolver needs."""
    canonical, old, promulgation, meta = {}, {}, {}, {}
    with csv_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lid, name = row["法令ID"].strip(), row["法令名"].strip()
            if not lid or not name:
                continue
            canonical[name] = lid
            meta[lid] = (name, row.get("法令種別", "").strip(), row.get("本文URL", "").strip())
            pnorm = resolver.normalize_promulgation(row.get("法令番号", ""))
            if pnorm:
                promulgation.setdefault(pnorm, lid)
            for o in row.get("旧法令名", "").split(","):
                o = o.strip()
                if o and o != name:
                    old[o] = lid
    return canonical, old, promulgation, meta


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", required=True, type=Path, help="dir with e-Gov XML + all_law_list.csv")
    ap.add_argument("--out", required=True, type=Path, help="output dir")
    ap.add_argument("--aliases", type=Path, default=Path(__file__).parent / "jlawcite" / "jp_law_aliases.json")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    canonical, old, prom, meta = load_law_list(args.corpus / "all_law_list.csv")
    aliases = resolver.load_aliases(args.aliases)
    idx = resolver.LawNameIndex(canonical_to_id=canonical, promulgation_to_id=prom,
                                alias_to_canonical=aliases, old_to_id=old)
    id_name = {lid: m[0] for lid, m in meta.items()}
    print(f"[build] laws={len(meta)} aliases={len(aliases)}", file=sys.stderr)

    def antecedent(pre: str):
        """Resolve the law named just before an in-law definition ((以下「旧法」という))."""
        cuts = list(_AMEND_CUT.finditer(pre))
        seg = (pre[cuts[-1].end():].strip() or pre) if cuts else pre
        m = _LAWNAME_TAIL.search(seg.strip())
        cand = m.group(1) if m else seg.strip()
        trimmed, _ = idx.trim_overgrab(cand)
        hit = idx.resolve(trimmed, None)
        return hit.law_id if hit else None

    xmls = sorted(args.corpus.glob("*/*.xml")) or sorted(args.corpus.glob("*.xml"))
    print(f"[build] xml files: {len(xmls)}", file=sys.stderr)

    # nodes
    with (args.out / "laws.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["law_id", "name", "type", "url"])
        for lid, (nm, ty, url) in meta.items():
            w.writerow([lid, nm, ty, url])

    l2l = Counter()
    n_ext = 0
    with gzip.open(args.out / "cites_edges.jsonl.gz", "wt", encoding="utf-8") as edges_fp:
        for k, xf in enumerate(xmls):
            if (k + 1) % 3000 == 0:
                print(f"  {k+1}/{len(xmls)} edges={n_ext}", file=sys.stderr)
            try:
                recs, _e, _s = xmlp.parse_law_xml(xf)
            except Exception:
                continue
            src = xf.stem.split("_")[0]
            srcname = id_name.get(src, "")
            texts = [r for r in recs if r.text]
            # per-law definition map for anaphora
            defs = {}
            for label, pre in citation.extract_local_definitions("\n".join(r.text for r in texts)):
                if label not in defs and (t := antecedent(pre)):
                    defs[label] = t
            for r in texts:
                for er in citation.extract_external(r.text)[0]:
                    name, plen = idx.trim_overgrab(er.law_name_raw)
                    tgt, via, conf = defs.get(name), "local_def", 0.9
                    if not tgt:
                        res = idx.resolve(name, er.promulgation)
                        if res:
                            tgt, via, conf = res.law_id, res.via, res.confidence
                        else:
                            tok = next((t for t in ANAPHORA_TOKENS if name.endswith(t) and t in defs), None)
                            if tok:
                                tgt, via, conf = defs[tok], "local_def_tail", 0.85
                    if not tgt:
                        continue
                    art = "-".join([str(er.article_num)] + [str(e) for e in er.eda]) if er.eda else str(er.article_num)
                    edges_fp.write(json.dumps({
                        "src_law_id": src, "src_law": srcname, "src_article": r.article_path,
                        "tgt_law_id": tgt, "tgt_law": id_name.get(tgt, ""), "tgt_article": art,
                        "via": via, "confidence": conf}, ensure_ascii=False) + "\n")
                    n_ext += 1
                    if tgt != src:
                        l2l[(src, tgt)] += 1

    with (args.out / "cites_law_to_law.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["src_law_id", "src_law", "tgt_law_id", "tgt_law", "n_citations"])
        for (s, t), c in sorted(l2l.items(), key=lambda x: -x[1]):
            w.writerow([s, id_name.get(s, ""), t, id_name.get(t, ""), c])

    print(f"[build] DONE: nodes={len(meta)} external_edges={n_ext:,} law_pairs={len(l2l):,}", file=sys.stderr)


if __name__ == "__main__":
    main()
