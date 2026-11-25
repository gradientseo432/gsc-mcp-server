# gsc-mcp-server

A **read-only** [MCP](https://modelcontextprotocol.io) server for **Google Search Console**. It lets an AI client
(Claude Code, Claude Desktop, Cursor, Antigravity...) answer questions like *"which pages lost traffic this month?"*
or *"which queries are one push away from page one?"* directly from your own Search Console data.

It is not a thin wrapper around the API: besides raw queries it ships the analyses an SEO actually runs, computed
server-side so the model gets a short, ranked answer instead of 25,000 rows.

## Tools

| Tool | What it answers |
|---|---|
| `list_sites` | Which properties can I read, and with what permission? |
| `search_analytics` | Raw query for an explicit date range, any dimensions, with page/query/country/device filters. |
| `top_queries` / `top_pages` | Top queries or pages by clicks, optionally scoped to a path or term. |
| `compare_periods` | Last N days vs the previous N days, per page or query (new / lost / up / down). |
| `traffic_drops` | Pages or queries that lost >= X % of their clicks, biggest absolute loss first. |
| `ctr_opportunities` | Queries with a CTR far below what *your own site* gets at that position (rewrite candidates). |
| `striking_distance` | Queries/pages ranking 8-20 with real impressions: the cheapest wins. |
| `position_buckets` | How many queries sit in 1-3, 4-10, 11-20, 21-50, 51+. |
| `keyword_cannibalization` | Queries where two or more of your pages share the impressions. |
| `inspect_url` | URL Inspection: index status, Google-selected canonical, last crawl, mobile usability. |

Design choices worth knowing:

- **Read-only.** The only OAuth scope requested is `webmasters.readonly`. The server cannot change anything in your property.
- **No external benchmarks.** `ctr_opportunities` compares each query with the median CTR *of the same site at the same
  position* (needs >= 3 data points per position), instead of a generic CTR curve that would not fit your SERPs.
- **Data lag handled.** Date ranges end 3 days ago because recent Search Console data is incomplete.
- **Capped output.** Every tool caps its rows so results stay small enough for an LLM context.
- **Credentials stay local.** The refresh token lives in `~/.config/gsc-mcp-server/token.json` and is never printed or logged.

## Setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project, enable the **Google Search Console API**,
   and create an **OAuth client ID of type "Desktop app"**. Download the JSON.
2. Install:
   ```bash
   pip install git+https://github.com/gradientseo432/gsc-mcp-server
   ```
3. Authorize once (opens the browser, read-only consent):
   ```bash
   export GSC_OAUTH_CLIENT_SECRETS=/path/to/client_secret.json
   gsc-mcp-server auth
   ```
4. Register it with your client.

   **Claude Code**
   ```bash
   claude mcp add gsc -- gsc-mcp-server
   ```
   **Claude Desktop / Cursor** (`mcpServers` in the client's JSON config)
   ```json
   {
     "mcpServers": {
       "gsc": { "command": "gsc-mcp-server" }
     }
   }
   ```

Environment variables: `GSC_OAUTH_CLIENT_SECRETS` (OAuth client file, default `./client_secret.json`) and
`GSC_TOKEN_PATH` (token location, default `~/.config/gsc-mcp-server/token.json`).

## Example prompts

- "List my sites, then show the pages that lost more than 30 % of their clicks in the last 28 days."
- "Which queries rank between 8 and 15 with more than 100 impressions? Group them by page."
- "Find CTR opportunities for `/blog/` and propose new titles for the top 5."
- "Do any of my pages cannibalize each other for the same query?"
- "Is `https://example.com/pricing` indexed, and which canonical did Google pick?"

## Development

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

The analysis logic (`src/gsc_mcp/analysis.py`) is pure Python with no network access; the server tests use a fake
Google service, so the suite needs no credentials.

## Limitations

- Search Console API quotas apply; very large properties return the top rows only (the API caps rows per request).
- `inspect_url` uses the URL Inspection API, which has its own daily per-property limit.
- Anonymized queries are not returned by Search Console, so totals from the UI can differ from summed rows.

## License

MIT. See [LICENSE](LICENSE).
