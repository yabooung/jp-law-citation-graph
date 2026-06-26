#!/usr/bin/env python3
"""Mine standard law abbreviations from the corpus's own in-text definitions.

Japanese statutes define abbreviations explicitly, e.g.
    金融商品取引法（昭和二十三年法律第二十五号。以下「金商法」という。）
This harvests every such definition across the corpus, resolves the antecedent
full law name → law, and aggregates globally. An abbreviation is kept only when
*standard*: defined in ≥2 distinct laws all pointing to the same law (≥80%
dominance), specific (length ≥4, law-suffix), free of version/clause prefixes,
and not already canonical/alias. This recovers genuine citations where a law
uses a standard abbreviation WITHOUT defining it.

    python mine_abbreviations.py --corpus <dir> --out mined_aliases.json

Deterministic; the output is merged into jlawcite/jp_law_aliases.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from jlawcite import citation, resolver, parser as xmlp

_CUT = re.compile(r"改正(?:後|前)の")
_TAIL = re.compile(r"([一-鿿々ヶ、]{2,60}?(?:法律|施行令|施行規則|法|令|規則|条例|条約))$")
_NOISE = re.compile(r"準用|改正|新|旧|年|平成|令和|昭和|当該|この|附則|前の|後の")
ANAPHORA = {"新法", "旧法", "新令", "旧令", "新規則", "旧規則", "同法", "本法", "現行法"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    canon, old, prom = {}, {}, {}
    with (args.corpus / "all_law_list.csv").open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lid, nm = row["法令ID"].strip(), row["法令名"].strip()
            if lid and nm:
                canon[nm] = lid
            p = resolver.normalize_promulgation(row.get("法令番号", ""))
            if p:
                prom.setdefault(p, lid)
            for o in row.get("旧法令名", "").split(","):
                o = o.strip()
                if o and o != nm:
                    old[o] = lid
    aliases = resolver.load_aliases(Path(__file__).parent / "jlawcite" / "jp_law_aliases.json")
    idx = resolver.LawNameIndex(canonical_to_id=canon, promulgation_to_id=prom,
                                alias_to_canonical=aliases, old_to_id=old)
    id_name = {v: k for k, v in canon.items()}

    def antecedent(pre):
        cs = list(_CUT.finditer(pre))
        seg = (pre[cs[-1].end():].strip() or pre) if cs else pre
        m = _TAIL.search(seg.strip())
        c = m.group(1) if m else seg.strip()
        t, _ = idx.trim_overgrab(c)
        r = idx.resolve(t, None)
        return r.law_id if r else None

    tgt_count = defaultdict(Counter)
    def_laws = defaultdict(set)
    xmls = sorted(args.corpus.glob("*/*.xml")) or sorted(args.corpus.glob("*.xml"))
    for k, xf in enumerate(xmls):
        if (k + 1) % 3000 == 0:
            print(f"  {k+1}/{len(xmls)}", file=sys.stderr)
        try:
            recs, _, _ = xmlp.parse_law_xml(xf)
        except Exception:
            continue
        src = xf.stem.split("_")[0]
        full = "\n".join(r.text for r in recs if r.text)
        for label, pre in citation.extract_local_definitions(full):
            if label in ANAPHORA or len(label) < 4 or _NOISE.search(label):
                continue
            if label in canon or label in old or label in aliases:
                continue
            tl = antecedent(pre)
            if tl and tl != src:
                tgt_count[label][tl] += 1
                def_laws[label].add(src)

    mined = {}
    for label, cnt in tgt_count.items():
        total = sum(cnt.values())
        top, n = cnt.most_common(1)[0]
        if len(def_laws[label]) >= 2 and n / total >= 0.8 and id_name.get(top) in canon:
            mined[label] = id_name[top]
    json.dump(mined, args.out.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[mine] {len(mined)} standard abbreviations → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
