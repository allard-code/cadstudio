# CAD-Studio – notes for Claude Code

Parametric CAD editor + MCP server. Python package `cadstudio/`, runs as one FastAPI process:
web editor on `/`, REST API on `/api/*`, MCP (streamable HTTP) on `/mcp`, signed downloads on `/dl/*`.
License: GPL-3.0-or-later (add `# SPDX-License-Identifier: GPL-3.0-or-later` to new source files).

## Layout
- `cadstudio/project.py` – project model (JSON on disk in `$CADSTUDIO_HOME/projects/<name>/project.json`), part evaluation (build123d code assigning `result`), cache, tessellation + vertex weld (watertight meshes).
- `cadstudio/export3mf.py` – 3MF (flavor `orca`: components + `Metadata/model_settings.config` with an extruder per part; flavor `prusa`: `Slic3r_PE_model.config` volume ranges), STL, STEP.
- `cadstudio/render.py` – headless numpy z-buffer renderer for `render_preview` and `render_assembly` (see-through,
  section, explode; no OpenGL).
- `cadstudio/mcp_server.py` – MCP tools (works with MCP SDK 1.x `FastMCP` and 2.x `MCPServer`); `main()` = stdio mode.
- `cadstudio/web.py` – FastAPI app, token auth middleware (`CADSTUDIO_TOKEN`: Bearer / x-api-key / cookie / `?token=`), MCP routes mounted, SSE `/api/events` for live updates.
- `cadstudio/links.py` – public URL, token, HMAC-signed download links, inbox folder.
- `cadstudio/static/` – editor (three.js r170 vendored in `static/vendor`, no CDN); UI strings in `static/i18n.js` (EN + NL).
- `claude-plugin/` + `.claude-plugin/marketplace.json` – Claude Code plugin (MCP config + `cad-design` skill).
- `tests/` – pytest suite (model, export, render, web/auth, MCP over HTTP).

## Develop
```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
python -m cadstudio web                       # http://127.0.0.1:8765, no auth
CADSTUDIO_TOKEN=x python -m cadstudio serve   # server mode as in Docker
pytest -q && ruff check .                     # must pass before committing
docker compose up -d --build                  # container
```

## Conventions
- Code, comments, docs, MCP tool descriptions and server messages in English. UI text only via `static/i18n.js` (keep `en` and `nl` keys in sync).
- Units mm, Z up, default bed 250×250×250. "Filament" = slot/extruder number (AMS / ACE Pro / MMU).
- MCP tools return user-code errors as `{"ok": false, "error", "traceback"}` instead of raising, so Claude can recover.
- Never write to stdout in stdio mode (it corrupts JSON-RPC); `mcp_server.main()` redirects fd 1.
- Docker versions are pinned in `requirements-docker.txt`; test locally when bumping.
- Record user-visible changes in `CHANGELOG.md` under "Unreleased"; releases are SemVer git tags (`v0.4.0`).
- **Every change merged to `main` is a release:** bump the version in `pyproject.toml` and `cadstudio/__init__.py`
  (patch = fixes only, minor = new features/tools, major = breaking), move "Unreleased" to `## [x.y.z] - date`
  in `CHANGELOG.md` in the same PR. No manual tag needed: when `main` gets a version without a `vx.y.z` tag, the
  `docker` workflow publishes `:x.y.z` / `:x.y` images and creates the tag + GitHub release itself.
