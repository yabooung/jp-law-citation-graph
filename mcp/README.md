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
| `pending_amendments(law)` | upcoming amendments: 施行日, amending law, 施行日備考 *(v2)* |
| `get_provision(citation)` | `民法第七百九条` → article text + what it cites / what cites it *(v2, needs index)* |
| `search_statutes(query)` | BM25 keyword or natural-language search over provisions *(v2, needs index)* |

The server ships in the `jlawcite` package (`jlawcite mcp`). On first start, if no data is found,
it downloads the latest snapshot in the background (as `jlawcite download` does): graph tools are
ready in seconds, `get_provision` / `search_statutes` after about 2 minutes. To use your own build,
set `JLAWCITE_DB` (search DB) and `JLAWCITE_DATA` (dir with laws.csv, cites_law_to_law.csv,
pending_versions.csv), or run it from a repo checkout.

Graph queries are deterministic; `resolve_citation` uses the same deterministic resolver as the
pipeline (built from the public law list — canonical + alias paths).

## Run
Claude Code, one line (needs [uv](https://docs.astral.sh/uv/)):
```bash
claude mcp add jlawcite -- uvx --from "jlawcite[mcp]" jlawcite mcp
```
Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "jlawcite": { "command": "uvx", "args": ["--from", "jlawcite[mcp]", "jlawcite", "mcp"] }
  }
}
```
Without uv: `pip install "jlawcite[mcp]"`, then use `jlawcite mcp` as the command.
Then ask, e.g., *"What laws cite 個人情報保護法?"* or *"Resolve the citations in this provision."*

## Example
```
get_law("民法")            → {law_id: 129AC0000000089, cites_count: 22, cited_by_count: 412, …}
what_cites("個人情報の保護に関する法律")  → 111 citing laws
citation_path("会社法", "民法")  → 会社法 → 民法 (1 hop)
```
