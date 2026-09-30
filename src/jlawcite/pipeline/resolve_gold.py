"""NTA 質疑応答事例 関係法令 → article-level gold (`eval/v2/nta_gold.jsonl`).

Usage:
    python -m jlawcite.pipeline.resolve_gold \
        --shitsugi data/raw/nta/shitsugi.jsonl \
        --nodes data/parsed/jp_nodes.jsonl \
        --output eval/v2/nta_gold.jsonl

Input: one JSON object per case with id, zeimu, url, title, shokai (question), kaito (answer) and
kankeihrei (list of 関係法令 lines). Output: one JSON object per case (query, answer, gold_articles, …),
sorted by id.

Rules (article level only):
  1. NFKC-normalize each 関係法令 line and split it on 「、」「，」. Law names that themselves
     contain 「、」 are protected first.
  2. A segment `<law>第N条(のM)*…` sets the current law; a bare `第N条…` inherits it, also across
     lines. Segments with only `第N項` / `第N号` point at the previous article and add nothing.
  3. Law name → law_id: Law node title (active first; for untitled laws the name in parentheses)
     → the alias file → a few NTA abbreviations → LawTitle@Abbrev when unambiguous.
  4. 通達, treaties, 告示 and names starting with an issue date are external (not gold);
     附則 and pre-amendment laws are out of scope.
  5. `{law_id}_a{article}` is gold if it is a main-provision Article node; otherwise unresolved.

The resolver used until 2.2 (`nta_processor`, removed in 2.4.0) kept only the first citation of each
line and attached 施行令 articles listed after a 施行令 name to the parent act.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_ALIASES = Path(__file__).resolve().parent.parent / "jp_law_aliases.json"

NTA_ALIAS = {
    "一般社団法": "一般社団法人及び一般財団法人に関する法律",
    "特定調停法": "特定債務等の調整の促進のための特定調停に関する法律",
    "災害減免法": "災害被害者に対する租税の減免、徴収猶予等に関する法律",
    "措置法": "租税特別措置法", "措置法施行令": "租税特別措置法施行令", "措置法施行規則": "租税特別措置法施行規則",
    "通則法": "国税通則法", "徴収法": "国税徴収法", "印紙法": "印紙税法",
}
EXTERNAL_MARKS = ("通達", "条約", "協定", "告示", "Q&A", "Q＆A", "議定書", "「")
EXTERNAL_DATE = re.compile(r"^(明治|大正|昭和|平成|令和)\d+年\d+月\d+日")  # 通達 issue date
OUT_OF_SCOPE = re.compile(r"附則|改正前|^旧|改正法|改正令|による改正")
COMMA_GUARD = "〓"  # placeholder for 「、」 inside a law name
REF = re.compile(r"^(?P<law>.*?)第(?P<art>\d+)条(?P<eda>(?:の\d+)*)")
ONLY_SUB = re.compile(r"^第\d+(?:項|号)")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s).replace(" ", "")


def load_law_index(nodes: Path, aliases_path: Path = DEFAULT_ALIASES):
    titles: dict[str, list[tuple[bool, str]]] = defaultdict(list)
    abbrevs: dict[str, set[str]] = defaultdict(set)
    articles: set[str] = set()
    with open(nodes, encoding="utf-8") as f:
        for line in f:
            head = line[:120]
            if '"type": "Law"' in head:
                d = json.loads(line)
                titles[nfkc(d["title"])].append((bool(d.get("is_active")), d["law_id"]))
                # untitled laws: 「昭和二十二年法律第百七十五号（災害被害者に…法律）」
                m = re.match(r"^.+?号[（(](.+)[）)]$", d["title"])
                if m:
                    titles[nfkc(m.group(1))].append((bool(d.get("is_active")), d["law_id"]))
                for ab in d.get("abbrevs") or []:
                    abbrevs[nfkc(ab)].add(d["law_id"])
            elif '"type": "Article"' in head:
                d = json.loads(line)
                if d.get("section") == "main" and "_asup" not in d["id"]:
                    articles.add(d["id"])
    title_index = {t: sorted(v, reverse=True)[0][1] for t, v in titles.items()}  # active first
    abbrev_index = {a: next(iter(v)) for a, v in abbrevs.items() if len(v) == 1}
    aliases = {nfkc(k): nfkc(v) for k, v in json.loads(aliases_path.read_text(encoding="utf-8")).items()
               if not k.startswith("_")}
    aliases.update({nfkc(k): nfkc(v) for k, v in NTA_ALIAS.items()})
    comma_titles = sorted({t for t in list(title_index) + list(aliases) + list(aliases.values()) if "、" in t},
                          key=len, reverse=True)
    return title_index, abbrev_index, aliases, articles, comma_titles


def resolve_law(name: str, title_index, abbrev_index, aliases) -> str | None:
    name = name.strip("「」『』()（）")
    for cand in (name, aliases.get(name)):
        if cand and cand in title_index:
            return title_index[cand]
    return abbrev_index.get(name)


def parse_refs(lines: list[str], comma_titles: list[str] = ()):
    """→ [(law_name, article_path, raw_segment)] at article level, duplicates kept."""
    out, law = [], None
    for line in lines:
        line = nfkc(line)
        for t in comma_titles:  # keep 「減免、徴収猶予等に関する法律」 in one piece
            if t in line:
                line = line.replace(t, t.replace("、", COMMA_GUARD))
        for seg in re.split(r"[、，,]", line):
            seg = seg.replace(COMMA_GUARD, "、")
            if not seg:
                continue
            m = REF.match(seg)
            if m:
                name = re.sub(r"\(.*?\)", "", m.group("law"))
                if name:
                    law = name
                if law:
                    eda = [e for e in m.group("eda").split("の") if e]
                    out.append((law, "-".join([m.group("art"), *eda]), seg))
            elif ONLY_SUB.match(seg):
                continue
            elif "第" not in seg:
                law = seg or law  # law name alone (e.g. "所得税法")
    return out


def resolve_case(c: dict, index, stats: Counter, unres_law: Counter) -> dict:
    title_index, abbrev_index, aliases, articles, comma_titles = index
    gold, external, out_scope, unresolved = [], [], [], []
    for law, path, raw in parse_refs(c["kankeihrei"], comma_titles):
        stats["refs"] += 1
        if any(x in law for x in EXTERNAL_MARKS) or EXTERNAL_DATE.match(law):
            external.append(raw); stats["external"] += 1
            continue
        if OUT_OF_SCOPE.search(law):
            out_scope.append(raw); stats["out_of_scope"] += 1
            continue
        lid = resolve_law(law, title_index, abbrev_index, aliases)
        if not lid:
            unresolved.append(raw); stats["unresolved_law"] += 1; unres_law[law] += 1
            continue
        aid = f"{lid}_a{path}"
        if aid in articles:
            if aid not in gold:
                gold.append(aid)
            stats["resolved"] += 1
        else:
            unresolved.append(raw); stats["unresolved_article"] += 1
    stats["cases"] += 1
    stats["cases_with_gold"] += bool(gold)
    return {"id": c["id"], "zeimu": c["zeimu"], "url": c["url"], "title": c["title"],
            "query": c["shokai"], "answer": c["kaito"], "kankeihrei": c["kankeihrei"],
            "gold_articles": gold, "external_refs": external, "out_of_scope_refs": out_scope,
            "unresolved": unresolved}


def main(argv=None):
    ap = argparse.ArgumentParser(description="NTA 質疑応答事例 → article-level gold")
    ap.add_argument("--shitsugi", required=True, type=Path, help="collected cases (JSONL)")
    ap.add_argument("--nodes", required=True, type=Path, help="parsed nodes (data/parsed/jp_nodes.jsonl)")
    ap.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES, help="law alias JSON")
    ap.add_argument("--output", required=True, type=Path, help="gold JSONL")
    a = ap.parse_args(argv)

    index = load_law_index(a.nodes, a.aliases)
    stats, unres_law = Counter(), Counter()
    with open(a.shitsugi, encoding="utf-8") as f:
        rows = [resolve_case(json.loads(line), index, stats, unres_law) for line in f if line.strip()]
    rows.sort(key=lambda r: r["id"])
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    report = {"stats": dict(stats), "top_unresolved_law": unres_law.most_common(25)}
    print(json.dumps(report, ensure_ascii=False, indent=1), file=sys.stderr)


if __name__ == "__main__":
    main()
