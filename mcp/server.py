#!/usr/bin/env python3
"""JLaw-CiteGraph MCP server — kept for old configs that run `python mcp/server.py`.

The server now ships in the package: `pip install "jlawcite[mcp]"` and run `jlawcite mcp`
(or `uvx --from "jlawcite[mcp]" jlawcite mcp`). See mcp/README.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from jlawcite.pipeline.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
