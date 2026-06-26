# JLaw-CiteGraph MCP server

Expose the Japanese statutory citation graph + deterministic resolver to LLMs
(Claude, etc.) over the [Model Context Protocol](https://modelcontextprotocol.io).
An LLM can resolve citation strings to specific laws and **traverse the citation
network for grounding** — something a text-only law lookup cannot do.

## Tools
| tool | what it does |
|---|---|
| `resolve_citation(text)` | parse Japanese legal text → resolved law citations (`会社法第737条` → law + article + `via`) |
| `what_cites(law)` | laws that cite the given law (incoming) |
| `what_law_cites(law)` | laws cited by the given law (outgoing) |
| `citation_path(a, b)` | shortest citation path between two laws (≤4 hops) |
| `get_law(query)` | law metadata + in/out degree + e-Gov link |

Graph queries are deterministic; `resolve_citation` uses the same deterministic resolver as the
pipeline (built from the public law list — canonical + alias paths).

## Run
```bash
pip install -r requirements.txt          # mcp SDK
python server.py                         # stdio MCP server
```

### Connect to Claude Desktop / Claude Code
Add to your MCP config (e.g. `claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "jlaw-citegraph": { "command": "python", "args": ["/abs/path/to/mcp/server.py"] }
  }
}
```
Then ask, e.g., *"What laws cite 個人情報保護法?"* or *"Resolve the citations in this provision."*

## Example
```
get_law("民法")            → {law_id: 129AC0000000089, cites_count: 22, cited_by_count: 412, …}
what_cites("個人情報の保護に関する法律")  → 110 citing laws
citation_path("会社法", "民法")  → 会社法 → 民法 (1 hop)
```
