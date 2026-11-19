# CAD-Studio – notities voor Claude Code

Parametrische CAD-editor + MCP-server. Python-pakket `cadstudio/`, draait als één FastAPI-proces:
web-editor op `/`, REST-API op `/api/*`, MCP (streamable HTTP) op `/mcp`, ondertekende downloads op `/dl/*`.

## Structuur
- `cadstudio/project.py` – projectmodel (JSON op schijf in `$CADSTUDIO_HOME/projects/<naam>/project.json`), part-evaluatie (build123d-code met `result`), cache, tessellatie + vertex-weld (waterdichte meshes).
- `cadstudio/export3mf.py` – 3MF (flavor `orca`: components + `Metadata/model_settings.config` met extruder per part; flavor `prusa`: `Slic3r_PE_model.config` volume-ranges), STL, STEP.
- `cadstudio/render.py` – headless numpy z-buffer renderer voor `render_preview` (geen OpenGL).
- `cadstudio/mcp_server.py` – MCP-tools (werkt met MCP SDK 1.x `FastMCP` én 2.x `MCPServer`); `main()` = stdio-modus.
- `cadstudio/web.py` – FastAPI-app, token-auth middleware (`CADSTUDIO_TOKEN`: Bearer / x-api-key / cookie / `?token=`), MCP-routes ingehangen, SSE `/api/events` voor live updates.
- `cadstudio/links.py` – public URL, token, HMAC-ondertekende downloadlinks, inbox-map.
- `cadstudio/static/` – editor (three.js r170 meegeleverd in `static/vendor`, geen CDN).
- `claude-plugin/` + `.claude-plugin/marketplace.json` – Claude Code-plugin (MCP-config + skill `cad-design`).

## Ontwikkelen
```bash
python -m venv .venv && . .venv/bin/activate && pip install -e .
python -m cadstudio web            # http://127.0.0.1:8765, geen auth
CADSTUDIO_TOKEN=x python -m cadstudio serve   # server-modus zoals in Docker
docker compose up -d --build       # container
```
Snelle check na wijzigingen: `python -m pyflakes cadstudio/*.py` en een MCP-ronde (`set_part` → `render_preview` → `export_3mf`).

## Afspraken
- Gebruikersteksten (UI, tool-beschrijvingen, foutmeldingen) in het Nederlands.
- Eenheden mm, Z omhoog, bed = 250×250×250 (Kobra S1). Filament-slot = ACE Pro-slot.
- MCP-tools geven fouten in user-code terug als `{"ok": false, "error", "traceback"}` i.p.v. te raisen, zodat Claude kan herstellen.
- Niets naar stdout schrijven in stdio-modus (corrumpeert JSON-RPC); `mcp_server.main()` leidt fd 1 om.
- Docker-versies staan vast in `requirements-docker.txt`; bij updaten eerst lokaal testen.
