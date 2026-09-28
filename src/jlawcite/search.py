"""Embedding-free search over the parsed graph (SQLite + FTS5 trigram).

Three access paths, all from one local SQLite file:

1. Keyword search — BM25 over *chunks*. A chunk is one Paragraph /
   SupplParagraph with its Items appended (the smallest unit that reads as a
   complete provision), or one Attachment. Terms of 3+ characters use the
   FTS5 trigram index; 1–2 character terms (common in Japanese: 解雇, 税額)
   fall back to substring filtering.
2. Citation lookup — 「民法第七百九条」, 「所得税法施行令14条2項」, 「民法附則第3条」
   are parsed and resolved with the same LawNameIndex the ingest uses
   (canonical titles, promulgation numbers, aliases, 旧法令名).
3. Graph navigation — outgoing / incoming CITES, DELEGATES_TO,
   REFERS_TO_ATTACHMENT, AMENDS for any node (an Article aggregates its
   Paragraphs and Items), plus pending amendments per law.

Build once with `build_index(parsed_dir, db_path)`, then open `SearchDB(db_path)`.
The CLI wrapper is `pipeline/search.py` (`jlawcite`).
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .resolver import (
    LawNameIndex,
    load_aliases,
    normalize_promulgation,
)
from .numerals import NUMERAL_RE, kanji_to_int

SCHEMA_VERSION = "search-v1"

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE laws (
    law_id TEXT PRIMARY KEY, title TEXT, promulgation_no TEXT, law_type TEXT,
    enforcement_date TEXT, is_active INTEGER, next_enforcement_date TEXT,
    pending_version_count INTEGER, mst_id TEXT
);
CREATE TABLE law_names (name TEXT, law_id TEXT, kind TEXT);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY, type TEXT, law_id TEXT, parent_id TEXT, section TEXT,
    article_path TEXT, paragraph_num INTEGER, item_path TEXT, suppl_tag TEXT,
    title TEXT, text TEXT, seq INTEGER, suppl_amend_law_num TEXT
);
CREATE TABLE edges (
    source TEXT, target TEXT, rel TEXT, raw TEXT, extracted_from TEXT,
    fallback_level TEXT, confidence REAL
);
CREATE TABLE pending (
    law_id TEXT, law_title TEXT, mst_id TEXT, enforcement_date TEXT,
    enforcement_note TEXT, amend_law_name TEXT, amend_law_num TEXT,
    amend_promulgation_date TEXT, supersedes_mst_id TEXT, url TEXT
);
CREATE TABLE chunks (
    rowid INTEGER PRIMARY KEY, node_id TEXT UNIQUE, law_id TEXT, article_id TEXT,
    section TEXT, heading TEXT, body TEXT
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    heading, body, content='chunks', content_rowid='rowid', tokenize='trigram'
);
"""

_INDEXES = """
CREATE INDEX idx_law_names ON law_names(name);
CREATE INDEX idx_nodes_law ON nodes(law_id, seq);
CREATE INDEX idx_nodes_parent ON nodes(parent_id);
CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_pending_law ON pending(law_id);
CREATE INDEX idx_chunks_law ON chunks(law_id);
"""

_LAW_TYPE_CODES = {"AC": "act", "CO": "cabinet_order", "IO": "imperial_order",
                   "DF": "dajokan", "DT": "dajokan"}


def law_type_of(law_id: str) -> str:
    code = law_id[3:5]
    if code in _LAW_TYPE_CODES:
        return _LAW_TYPE_CODES[code]
    if code.startswith("M") or code.startswith("R"):
        return "ministerial"
    return "other"


def _jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build_index(
    parsed_dir: Path,
    db_path: Path,
    csv_path: Path | None = None,
    aliases_path: Path | None = None,
    progress: bool = True,
) -> dict:
    """Build the search DB from `ingest_full` outputs. Overwrites `db_path`."""
    def log(msg: str) -> None:
        if progress:
            print(f"[search.build] {msg}", flush=True)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(db_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")
    con.executescript(_SCHEMA)

    # ---- nodes + chunks (single pass; nodes are in document order) ----
    log("nodes / chunks …")
    art_title: dict[str, str] = {}
    law_title: dict[str, str] = {}
    chunk_rows: list[list] = []      # [node_id, law_id, article_id, section, heading, body]
    chunk_pos: dict[str, int] = {}   # paragraph id → index in chunk_rows
    node_batch: list[tuple] = []
    law_rows: list[tuple] = []
    abbrev_claims: dict[str, set[str]] = {}
    n_nodes = 0
    for seq, n in enumerate(_jsonl(parsed_dir / "jp_nodes.jsonl")):
        t = n["type"]
        nid = n["id"]
        if t == "Law":
            law_title[nid] = n["title"]
            for ab in n.get("abbrevs") or []:
                abbrev_claims.setdefault(ab, set()).add(nid)
            law_rows.append((
                nid, n["title"], n.get("promulgation_no"), law_type_of(nid),
                n.get("enforcement_date"), int(bool(n.get("is_active", True))),
                n.get("next_enforcement_date"), n.get("pending_version_count", 0),
                n.get("mst_id"),
            ))
        elif t in ("Article", "SupplArticle"):
            art_title[nid] = n["title"]
        elif t in ("Paragraph", "SupplParagraph"):
            art_id = n["parent_id"]
            lt = law_title.get(n["law_id"], n.get("law_title", ""))
            heading = f"{lt} {art_title.get(art_id, '')}".strip()
            if n.get("paragraph_num") and n["paragraph_num"] > 1:
                heading += f" 第{n['paragraph_num']}項"
            if t == "SupplParagraph" and not art_title.get(art_id, "").startswith("附則"):
                heading = f"{lt} 附則 {art_title.get(art_id, '')}".strip()
            chunk_pos[nid] = len(chunk_rows)
            chunk_rows.append([nid, n["law_id"], art_id, n.get("section", "main"),
                               heading, n.get("text") or ""])
        elif t == "Item":
            pos = chunk_pos.get(n["parent_id"])
            if pos is not None and n.get("text"):
                chunk_rows[pos][5] += "\n" + n["text"]
        elif t == "Attachment":
            lt = law_title.get(n["law_id"], "")
            chunk_rows.append([nid, n["law_id"], None, "main",
                               f"{lt} {n['title']}".strip(), n.get("text") or ""])
        node_batch.append((
            nid, t, n.get("law_id"), n.get("parent_id"), n.get("section"),
            n.get("article_path"), n.get("paragraph_num"),
            n.get("item_path") or (str(n["item_num"]) if n.get("item_num") is not None else None),
            n.get("suppl_tag"), n.get("title"), n.get("text") or "", seq,
            n.get("suppl_amend_law_num"),
        ))
        n_nodes += 1
        if len(node_batch) >= 50_000:
            con.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", node_batch)
            node_batch.clear()
    con.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", node_batch)
    con.executemany("INSERT INTO laws VALUES (?,?,?,?,?,?,?,?,?)", law_rows)
    con.executemany(
        "INSERT INTO chunks(node_id, law_id, article_id, section, heading, body) "
        "VALUES (?,?,?,?,?,?)", chunk_rows)
    log(f"  {n_nodes:,} nodes, {len(law_rows):,} laws, {len(chunk_rows):,} chunks")

    # ---- law names (for citation lookup) ----
    names: list[tuple[str, str, str]] = [(title, lid, "canonical") for lid, title in law_title.items()]
    for lid, _t, prom, *_ in law_rows:
        key = normalize_promulgation(prom) if prom else None
        if key:
            names.append((key, lid, "promulgation"))
    # Official short names (LawTitle@Abbrev), unambiguous ones only
    names += [(ab, next(iter(ids)), "abbrev") for ab, ids in abbrev_claims.items()
              if len(ids) == 1]
    if aliases_path and aliases_path.exists():
        title_to_id = {t: lid for lid, t in law_title.items()}
        for alias, canonical in load_aliases(aliases_path).items():
            if canonical in title_to_id:
                names.append((alias, title_to_id[canonical], "alias"))
    if csv_path and csv_path.exists():
        with csv_path.open(encoding="utf-8-sig") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if len(row) > 11 and row[4] and row[11] in law_title:
                    for old in row[4].split(","):
                        if old.strip():
                            names.append((old.strip(), row[11], "old_name"))
    con.executemany("INSERT INTO law_names VALUES (?,?,?)", names)

    # ---- edges ----
    log("edges …")
    n_edges = 0
    for fname in ("jp_cites_edges.jsonl", "jp_delegates_edges.jsonl",
                  "jp_attaches_edges.jsonl", "jp_amends_edges.jsonl"):
        fp = parsed_dir / fname
        if not fp.exists():
            continue
        batch = []
        for e in _jsonl(fp):
            batch.append((e["source"], e["target"], e["rel"], e.get("raw"),
                          e.get("extracted_from"), e.get("fallback_level"),
                          e.get("confidence")))
            if len(batch) >= 100_000:
                con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?)", batch)
                n_edges += len(batch)
                batch.clear()
        con.executemany("INSERT INTO edges VALUES (?,?,?,?,?,?,?)", batch)
        n_edges += len(batch)
    log(f"  {n_edges:,} edges")

    # ---- pending versions ----
    fp = parsed_dir / "jp_pending_versions.jsonl"
    if fp.exists():
        con.executemany(
            "INSERT INTO pending VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(p["law_id"], p.get("law_title"), p["mst_id"], p["enforcement_date"],
              p.get("enforcement_note"), p.get("amend_law_name"), p.get("amend_law_num"),
              p.get("amend_promulgation_date"), p.get("supersedes_mst_id"), p.get("url"))
             for p in _jsonl(fp)])

    log("indexes + FTS (trigram) …")
    con.executescript(_INDEXES)
    con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")

    meta = {"schema": SCHEMA_VERSION, "nodes": n_nodes, "laws": len(law_rows),
            "chunks": len(chunk_rows), "edges": n_edges}
    snap = parsed_dir / "jp_parse_stats.json"
    if snap.exists():
        meta["as_of"] = json.loads(snap.read_text(encoding="utf-8")).get("as_of")
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
    con.commit()
    con.execute("VACUUM")
    con.close()
    if db_path.exists():
        db_path.unlink()
    tmp.rename(db_path)
    log(f"done → {db_path} ({db_path.stat().st_size / 1e9:.2f} GB)")
    return meta


# ---------------------------------------------------------------------------
# Citation-string parsing
# ---------------------------------------------------------------------------
_N = NUMERAL_RE
# Tolerant: 「第」 optional, arabic or kanji numerals, の-branches, 附則.
_CITE_PAT = re.compile(
    rf"^(?P<law>.*?)\s*(?P<suppl>附則)?\s*第?(?P<art>{_N})条(?P<eda>(?:の{_N})*)"
    rf"(?:\s*第?(?P<para>{_N})項)?"
    rf"(?:\s*第?(?P<item>{_N})号(?P<item_eda>(?:の{_N})*))?\s*$"
)


@dataclass
class ParsedCitation:
    law: str
    suppl: bool
    article_path: str
    paragraph: int | None
    item_path: str | None


def _path(head: str, eda: str) -> str:
    parts = [str(kanji_to_int(head))]
    parts += [str(kanji_to_int(x)) for x in re.findall(rf"の({_N})", eda or "")]
    return "-".join(parts)


def parse_citation(text: str) -> ParsedCitation | None:
    s = unicodedata.normalize("NFKC", text).strip()
    m = _CITE_PAT.match(s)
    if not m or kanji_to_int(m.group("art")) is None:
        return None
    return ParsedCitation(
        law=m.group("law").strip(),
        suppl=bool(m.group("suppl")),
        article_path=_path(m.group("art"), m.group("eda")),
        paragraph=kanji_to_int(m.group("para")) if m.group("para") else None,
        item_path=_path(m.group("item"), m.group("item_eda")) if m.group("item") else None,
    )


# ---------------------------------------------------------------------------
# Query side
# ---------------------------------------------------------------------------
class CitationLookupError(Exception):
    """Raised with a human-readable message when a lookup cannot be resolved."""


class SearchDB:
    def __init__(self, db_path: Path):
        if not Path(db_path).exists():
            raise FileNotFoundError(
                f"{db_path} not found — build it with `jlawcite index`")
        self.con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        self._index: LawNameIndex | None = None

    # ---- meta ----
    def stats(self) -> dict:
        out = {r["key"]: r["value"] for r in self.con.execute("SELECT * FROM meta")}
        out["pending_versions"] = self.con.execute("SELECT count(*) FROM pending").fetchone()[0]
        out["edges_by_rel"] = {r[0]: r[1] for r in self.con.execute(
            "SELECT rel, count(*) FROM edges GROUP BY rel")}
        return out

    # ---- law names ----
    @property
    def name_index(self) -> LawNameIndex:
        if self._index is None:
            by_kind: dict[str, dict[str, str]] = {"canonical": {}, "promulgation": {},
                                                  "alias": {}, "abbrev": {}, "old_name": {}}
            for r in self.con.execute("SELECT name, law_id, kind FROM law_names"):
                by_kind[r["kind"]].setdefault(r["name"], r["law_id"])
            titles = {lid: t for t, lid in by_kind["canonical"].items()}
            self._index = LawNameIndex(
                canonical_to_id=by_kind["canonical"],
                promulgation_to_id=by_kind["promulgation"],
                alias_to_canonical={a: titles[lid]
                                    for a, lid in {**by_kind["abbrev"], **by_kind["alias"]}.items()
                                    if lid in titles},
                old_to_id=by_kind["old_name"],
            )
        return self._index

    def resolve_law(self, name: str) -> dict:
        """Law row for a name / promulgation number / law_id. Raises with
        candidates when ambiguous."""
        name = unicodedata.normalize("NFKC", name).strip()
        row = self.con.execute("SELECT * FROM laws WHERE law_id = ?", (name,)).fetchone()
        if row:
            return dict(row)
        prom = normalize_promulgation(name)
        hit = self.name_index.resolve(name, prom if prom else None)
        if hit:
            return dict(self.con.execute("SELECT * FROM laws WHERE law_id = ?",
                                         (hit.law_id,)).fetchone())
        cands = self.con.execute(
            "SELECT law_id, title FROM laws WHERE title LIKE ? ORDER BY length(title) LIMIT 8",
            (f"%{name}%",)).fetchall()
        if len(cands) == 1:
            return dict(self.con.execute("SELECT * FROM laws WHERE law_id = ?",
                                         (cands[0]["law_id"],)).fetchone())
        if cands:
            lst = "\n".join(f"  {c['law_id']}  {c['title']}" for c in cands)
            raise CitationLookupError(f"'{name}' is ambiguous. Candidates:\n{lst}")
        raise CitationLookupError(f"law not found: '{name}'")

    # ---- nodes ----
    def node(self, node_id: str) -> dict | None:
        r = self.con.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return dict(r) if r else None

    def children(self, node_id: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM nodes WHERE parent_id = ? ORDER BY seq", (node_id,))]

    def _original_suppl_tag(self, law_id: str) -> str | None:
        """Tag of the enactment 附則: the first block without AmendLawNum
        (same rule as the ingest's `original_suppl`)."""
        r = self.con.execute(
            "SELECT suppl_tag FROM nodes WHERE law_id = ? AND type = 'SupplArticle' "
            "AND suppl_amend_law_num IS NULL ORDER BY seq LIMIT 1", (law_id,)).fetchone()
        return r["suppl_tag"] if r else None

    def lookup(self, query: str, law_hint: str | None = None) -> dict:
        """Resolve a node id or a citation string to a node, with context."""
        q = query.strip()
        n = self.node(q)
        if n:
            return self._with_context(n)
        pc = parse_citation(q)
        if pc is None:
            # A bare law name → the Law node
            law = self.resolve_law(q)
            return self._with_context(self.node(law["law_id"]))
        law = self.resolve_law(pc.law or law_hint or "")
        lid = law["law_id"]
        if pc.suppl:
            tag = self._original_suppl_tag(lid)
            if tag is None:
                raise CitationLookupError(
                    f"{law['title']} ({lid}): the e-Gov text has no enactment 附則 "
                    f"(only amending-law 附則 blocks) — search with --law instead")
            base = f"{lid}_asup-{tag}-{pc.article_path}"
        else:
            base = f"{lid}_a{pc.article_path}"
        candidates = [base]
        if pc.paragraph is not None:
            candidates.insert(0, f"{base}_p{pc.paragraph}")
            if pc.item_path:
                candidates.insert(0, f"{base}_p{pc.paragraph}_i{pc.item_path}")
        elif pc.item_path:
            candidates.insert(0, f"{base}_p1_i{pc.item_path}")
        for cid in candidates:
            n = self.node(cid)
            if n:
                out = self._with_context(n)
                if cid != candidates[0]:
                    out["note"] = f"exact target {candidates[0]} not found; showing {cid}"
                return out
        raise CitationLookupError(f"{law['title']} ({lid}) has no node {candidates[0]}")

    def _with_context(self, n: dict) -> dict:
        law = dict(self.con.execute("SELECT * FROM laws WHERE law_id = ?",
                                    (n["law_id"],)).fetchone())
        out = {"node": n, "law": law, "text": self.assemble_text(n["id"])}
        out["pending"] = self.pending(n["law_id"])
        return out

    def assemble_text(self, node_id: str) -> str:
        """Readable text for any node: an Article with all its Paragraphs and
        Items, a Paragraph with its Items, or the node's own text."""
        n = self.node(node_id)
        if n is None:
            return ""
        if n["type"] in ("Law", "Hierarchy"):
            return ""
        lines = []
        if n["type"] in ("Article", "SupplArticle"):
            lines.append(n["title"])
            for p in self.children(node_id):
                lines.append(self._para_line(p))
                lines += [self._item_line(i) for i in self.children(p["id"]) if i["text"]]
        elif n["type"] in ("Paragraph", "SupplParagraph"):
            lines.append(self._para_line(n))
            lines += [self._item_line(i) for i in self.children(node_id) if i["text"]]
        else:
            lines.append(n["text"])
        return "\n".join(lines)

    @staticmethod
    def _item_line(i: dict) -> str:
        # Item text is "一\n本文\nイ\n…": put the number and its sentence on one line
        return "  " + i["text"].replace("\n", "　", 1).replace("\n", "\n    ")

    @staticmethod
    def _para_line(p: dict) -> str:
        num = p.get("paragraph_num")
        prefix = f"{num} " if num and num > 1 else ""
        return prefix + (p.get("text") or "")

    def toc(self, law_id: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, type, title, parent_id FROM nodes WHERE law_id = ? "
            "AND type IN ('Hierarchy','Article') ORDER BY seq", (law_id,))]

    # ---- graph ----
    def refs(self, node_id: str, direction: str = "both",
             rels: Iterable[str] | None = None, limit: int = 200) -> dict:
        """Edges touching `node_id` and its descendants (Article → its
        Paragraphs/Items; Law → the whole law for incoming)."""
        rels = list(rels) if rels else None
        lo, hi = node_id, node_id + "_￿"   # id and every descendant id
        rel_sql = f" AND e.rel IN ({','.join('?' * len(rels))})" if rels else ""
        out = {}
        if direction in ("out", "both"):
            out["out"] = [dict(r) for r in self.con.execute(
                "SELECT e.*, t.title AS target_title, t.law_id AS target_law, "
                "l.title AS target_law_title FROM edges e "
                "LEFT JOIN nodes t ON t.id = e.target LEFT JOIN laws l ON l.law_id = t.law_id "
                f"WHERE (e.source = ? OR (e.source > ? AND e.source < ?)){rel_sql} "
                "LIMIT ?", (node_id, node_id + "_", hi, *(rels or []), limit))]
        if direction in ("in", "both"):
            out["in"] = [dict(r) for r in self.con.execute(
                "SELECT e.*, s.title AS source_title, s.law_id AS source_law, "
                "l.title AS source_law_title FROM edges e "
                "LEFT JOIN nodes s ON s.id = e.source LEFT JOIN laws l ON l.law_id = s.law_id "
                f"WHERE (e.target = ? OR (e.target > ? AND e.target < ?)){rel_sql} "
                "LIMIT ?", (lo, node_id + "_", hi, *(rels or []), limit))]
        return out

    def pending(self, law_id: str | None = None, until: str | None = None,
                limit: int = 200) -> list[dict]:
        sql, args = "SELECT * FROM pending WHERE 1=1", []
        if law_id:
            sql += " AND law_id = ?"
            args.append(law_id)
        if until:
            sql += " AND enforcement_date <= ?"
            args.append(until)
        sql += " ORDER BY enforcement_date, law_id LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.con.execute(sql, args)]

    # ---- keyword search ----
    def search(self, query: str, law: str | None = None, law_type: str | None = None,
               section: str = "all", include_inactive: bool = False,
               limit: int = 20, offset: int = 0, natural: bool = False) -> list[dict]:
        """BM25 keyword search over chunks.

        Keyword mode (default): whitespace-separated terms are ANDed. Terms ≥3
        chars use the trigram index; shorter ones are substring filters.
        Natural mode (`natural=True`): the query is a sentence (e.g. a
        question); its character trigrams are ORed and ranked by BM25 —
        a standard n-gram baseline for unsegmented Japanese.
        """
        if natural:
            grams = query_trigrams(query)
            if not grams:
                return []
            terms, long_terms, short_terms = grams, grams, []
            fts_join = " OR "
        else:
            terms = [unicodedata.normalize("NFKC", t) for t in query.split() if t.strip()]
            if not terms:
                return []
            long_terms = [t for t in terms if len(t) >= 3]
            short_terms = [t for t in terms if len(t) < 3]
            fts_join = " AND "
        where, args = [], []
        if long_terms:
            fts = fts_join.join('"' + t.replace('"', '""') + '"' for t in long_terms)
            base = ("SELECT c.*, bm25(chunks_fts, 2.0, 1.0) AS score, "
                    "snippet(chunks_fts, 1, '【', '】', '…', 48) AS snippet "
                    "FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid "
                    "WHERE chunks_fts MATCH ?")
            args.append(fts)
        else:
            base = "SELECT c.*, 0.0 AS score, NULL AS snippet FROM chunks c WHERE 1=1"
        for t in short_terms:
            where.append("(instr(c.body, ?) > 0 OR instr(c.heading, ?) > 0)")
            args += [t, t]
        if law:
            where.append("c.law_id = ?")
            args.append(self.resolve_law(law)["law_id"])
        if law_type or not include_inactive:
            sub = "SELECT law_id FROM laws WHERE 1=1"
            if law_type:
                sub += " AND law_type = ?"
                args.append(law_type)
            if not include_inactive:
                sub += " AND is_active = 1"
            where.append(f"c.law_id IN ({sub})")
        if section in ("main", "suppl"):
            where.append("c.section = ?")
            args.append(section)
        sql = base + "".join(" AND " + w for w in where)
        if long_terms:
            sql += " ORDER BY score"
        else:
            # No BM25 without an FTS term: rank by term frequency / length.
            freq = " + ".join(
                "(length(c.body) - length(replace(c.body, ?, ''))) / length(?)"
                for _ in short_terms)
            sql += f" ORDER BY ({freq}) * 1.0 / (length(c.body) + 50) DESC"
            args += [x for t in short_terms for x in (t, t)]
        sql += " LIMIT ? OFFSET ?"
        args += [limit, offset]
        rows = [dict(r) for r in self.con.execute(sql, args)]
        for r in rows:
            if not r.get("snippet"):
                r["snippet"] = _snippet(r["body"], terms)
        return rows


_CONTENT_RUN = re.compile(r"[一-鿿々〆ヵヶァ-ヴー0-9A-Za-z]{3,}")


def query_trigrams(text: str, max_terms: int = 64) -> list[str]:
    """Distinct character trigrams of the content runs (kanji / katakana /
    digits) of a natural-language query, in order. Hiragana (particles,
    inflection) is treated as a separator."""
    out: list[str] = []
    seen: set[str] = set()
    for run in _CONTENT_RUN.findall(unicodedata.normalize("NFKC", text)):
        for i in range(len(run) - 2):
            g = run[i:i + 3]
            if g not in seen:
                seen.add(g)
                out.append(g)
    return out[:max_terms]


def _snippet(body: str, terms: list[str], width: int = 60) -> str:
    pos = min((body.find(t) for t in terms if t in body), default=0)
    s = body[max(0, pos - width // 3): pos + width]
    for t in terms:
        s = s.replace(t, f"【{t}】")
    return ("…" if pos > width // 3 else "") + s.replace("\n", " ") + "…"
