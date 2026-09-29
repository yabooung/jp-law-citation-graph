"""jlawcite — deterministic Japanese statutory citation graph and search.

Modules (v1 names kept):
    parser      e-Gov 法令 XML → Law / Article / Paragraph / Item / Attachment records
    citation    rule-based citation extraction (external / internal / referential / …)
    resolver    LawNameIndex (promulgation / canonical / 旧法令名 / alias / defined
                abbreviations) and referential resolution (前条・同項・前号 …)
    search      SQLite FTS5 search index and SearchDB API
    pipeline    fetch → build → validate → export / index / eval  (CLI: `jlawcite`)
"""
from __future__ import annotations

__version__ = "2.1.0"
