"""Single command-line entry point.

    <prog> fetch     [--output DIR]           e-Gov bulk XML  (jlawcite.pipeline.fetch_egov)
    <prog> build     --input DIR --output DIR  XML → graph     (jlawcite.pipeline.ingest_full)
    <prog> validate  --data DIR                integrity checks (jlawcite.pipeline.validate)
    <prog> export    --out DIR                 release data files (jlawcite.pipeline.export_release)
    <prog> index     [--data DIR]              build the search DB
    <prog> search|get|refs|law|pending|stats   query the search DB (jlawcite.pipeline.search)
    <prog> eval      [--gold FILE]             NTA retrieval benchmark (jlawcite.pipeline.eval_search)
    <prog> versions  --output FILE             SUPERSEDES chain (jlawcite.pipeline.build_versions)

The search DB path defaults to $JLAWCITE_DB or data/search/jp_search.sqlite.
"""
from __future__ import annotations

import importlib
import sys

_MODULES = {
    "fetch": "fetch_egov",
    "build": "ingest_full",
    "validate": "validate",
    "export": "export_release",
    "eval": "eval_search",
    "versions": "build_versions",
}
_SEARCH = {"search", "get", "refs", "law", "pending", "stats"}


def _usage(prog: str) -> str:
    return __doc__.replace("<prog>", prog)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    prog = "jlawcite"
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage(prog))
        return 0
    cmd, rest = argv[0], argv[1:]
    pkg = "jlawcite.pipeline"
    if cmd in _MODULES:
        mod = importlib.import_module(f"{pkg}.{_MODULES[cmd]}")
        sys.argv = [f"{prog} {cmd}", *rest]
        result = mod.main()
        return result if isinstance(result, int) else 0
    search = importlib.import_module(f"{pkg}.search_cli")
    if cmd == "index":
        return search.main(["build", *rest])
    if cmd in _SEARCH:
        return search.main([cmd, *rest])
    print(f"unknown command: {cmd}\n\n{_usage(prog)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
