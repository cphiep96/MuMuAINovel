# MuMuAINovel first-party MCP server

`backend/app/mcp_server/` exposes the existing MuMuAINovel project, wizard,
chapter, prompt/style, and video-export services as MCP tools.  It uses the
installed `mcp==1.22.0` FastMCP implementation.

## Tools

- `mumu_auth_status`, `mumu_health`
- `list_projects`, `create_project`, `update_project`
- `list_categories`, `create_category`
- `wizard_world_building`, `wizard_career_system`, `wizard_characters`,
  `wizard_outline`, `wizard_world_regenerate`, `wizard_status`, `task_status`
- `list_chapters`, `create_chapter`, `generate_chapter`, `continue_chapters`
- `list_prompt_templates`, `list_writing_styles`
- `video_capabilities`, `create_video_export`, `list_video_exports`,
  `get_video_export`, `video_export_action`, `video_download_paths`

Wizard and chapter-generation tools call the app's existing REST/SSE routes;
project, taxonomy, prompt/style, and video tools reuse the SQLAlchemy/service
layer directly.  Video download returns safe server-side paths rather than
placing binary files in an MCP JSON response.

## Configuration

Set these environment variables in the MCP process (never commit secrets):

- `MUMU_API_BASE` (default `http://127.0.0.1:8000`)
- `MUMU_MCP_TOKEN` (shared bearer token; `MUMU_SESSION_TOKEN` is an alias)
- `MUMU_MCP_USER_ID` (or `MUMU_USER_ID`) for the isolated MuMu user
- `MUMU_MCP_TRANSPORT` (`stdio` by default), `MUMU_MCP_HOST`, and
  `MUMU_MCP_PORT` for optional HTTP transports

The regular FastAPI auth middleware accepts a matching `Authorization: Bearer`
token and `X-Mumu-User-ID` for MCP loopback calls.  Browser cookie sessions are
still supported unchanged.

## Run

From `backend/`:

```bash
MUMU_MCP_TOKEN=... MUMU_MCP_USER_ID=... python -m app.mcp_server
```

For Cursor/Claude/Grok, use stdio (the default). For the in-app plugin manager,
run streamable HTTP:

```bash
MUMU_MCP_TRANSPORT=streamable-http MUMU_MCP_HOST=127.0.0.1 \
  MUMU_MCP_PORT=8765 python -m app.mcp_server
```

The HTTP endpoint is `http://127.0.0.1:8765/mcp` and accepts
`Authorization: Bearer <MUMU_MCP_TOKEN>`. **Do not register that loopback URL
in the in-app plugin manager** — SSRF checks reject `127.0.0.1`, `localhost`,
and LAN addresses. Register a public HTTPS tunnel (or a public reverse-proxy
URL) instead, and call `/api/mcp/plugins` with a real browser session cookie
(`state.user` is required; a shared bearer token is not enough for that API).
See `docs/mcp-agent-guide.md` section 8.

## Taxonomy behavior

Genre categories are persisted on an existing project when `project_id` is
provided; career categories are updated on an existing career when
`career_id` is provided.  When no target record exists, both use a hidden
taxonomy marker in the existing prompt-template table so the category can be
created/listed without inventing a second persistence system.  Use the native
project/career APIs to create a complete career; this MCP category tool only
changes its category.
