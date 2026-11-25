# SPDX-License-Identifier: GPL-3.0-or-later
"""Web editor backend (FastAPI) + MCP over Streamable HTTP on /mcp, in one process.

Local:   python -m cadstudio web                 -> http://127.0.0.1:8765  (no auth)
Server:  python -m cadstudio serve --host 0.0.0.0 with CADSTUDIO_TOKEN set (Docker does this)
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import tempfile
from pathlib import Path

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import links
from . import project as P
from . import version as _version
from .export3mf import export_3mf, export_step, export_stl
from .render import render_assembly_png, render_png, save_assembly_png, thumbnail

STATIC = Path(__file__).parent / "static"


# --------------------------------------------------------------------------- MCP (streamable HTTP)

def _mcp_http_app():
    """Build the MCP streamable-HTTP Starlette app (SDK 2.x MCPServer or 1.x FastMCP)."""
    from mcp.server.transport_security import TransportSecuritySettings

    from .mcp_server import mcp

    # Host/Origin checks off: access is controlled by CADSTUDIO_TOKEN below, and behind a reverse proxy
    # / Cloudflare tunnel the Host header is your own domain.
    sec = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    try:  # SDK 2.x
        sub = mcp.streamable_http_app(streamable_http_path="/mcp", transport_security=sec, host="0.0.0.0")
    except TypeError:  # SDK 1.x
        mcp.settings.streamable_http_path = "/mcp"
        try:
            mcp.settings.transport_security = sec
        except Exception:
            pass
        sub = mcp.streamable_http_app()
    return mcp, sub


_mcp, _mcp_sub = _mcp_http_app()


@contextlib.asynccontextmanager
async def lifespan(_app):
    P.ensure_demo()
    async with _mcp.session_manager.run():
        yield


app = FastAPI(title="CAD-Studio", lifespan=lifespan)
# put the MCP route(s) directly on the main app, so "/mcp" works without a trailing-slash redirect
app.router.routes.extend(_mcp_sub.routes)


# --------------------------------------------------------------------------- auth

# /.well-known: there is no OAuth here; answering 404 (not 401) tells MCP clients such as claude.ai
# that no OAuth sign-in is needed, so they just send the configured header.
OPEN_PATHS = ("/static/", "/dl/", "/health", "/login", "/favicon.ico", "/.well-known/")

LOGIN_HTML = (STATIC / "login.html").read_text(encoding="utf-8")


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if auth and " " not in auth:  # bare token in the Authorization header (common connector misconfiguration)
        return auth
    return (request.headers.get("x-api-key") or request.headers.get("x-auth-token")
            or request.cookies.get("cs_token") or request.query_params.get("token"))


@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    """The editor and its API change whenever Claude edits the project (or the container is updated):
    never let a browser or a reverse proxy serve a stale copy (that's what made a hard refresh necessary)."""
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") or path == "/":
        resp.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith("/static/") and "/vendor/" not in path:
        resp.headers["Cache-Control"] = "no-cache"  # revalidate (cheap 304) instead of trusting a stale file
    return resp


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    expected = links.token()
    path = request.url.path
    if not expected or path.startswith(OPEN_PATHS):
        return await call_next(request)
    given = _token_from(request)
    if given and hmac.compare_digest(given, expected):
        # ?token=... on a page load -> remember in a cookie and clean the URL
        if request.method == "GET" and request.query_params.get("token") and not path.startswith(("/mcp", "/api")):
            resp = RedirectResponse(path)
            resp.set_cookie("cs_token", given, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
            return resp
        return await call_next(request)
    if path == "/":
        return HTMLResponse(LOGIN_HTML.replace("__ERR__", ""), status_code=401)
    return JSONResponse({"error": "unauthorized – send 'Authorization: Bearer <CADSTUDIO_TOKEN>'"}, status_code=401,
                        headers={"WWW-Authenticate": "Bearer"})


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    given = str(form.get("token", ""))
    expected = links.token()
    if expected and hmac.compare_digest(given, expected):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("cs_token", given, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
        return resp
    return HTMLResponse(LOGIN_HTML.replace("__ERR__", "<p class=e>Invalid token</p>"), status_code=401)


@app.get("/health")
def health():
    v = _version.info(check_updates=False)
    return {"ok": True, "project": P.current_project_name(), "version": v["version"], "commit": v["short"]}


@app.get("/api/version")
def version_info():
    """Running version/build, and whether a newer commit is published (cached GitHub lookup)."""
    return _version.info()


# --------------------------------------------------------------------------- pages

def _proj() -> P.Project:
    return P.get_project()


@app.exception_handler(P.PartError)
async def _part_error(_, exc: P.PartError):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# --------------------------------------------------------------------------- project API

@app.get("/api/project")
def get_project():
    return _proj().summary()


@app.get("/api/projects")
def projects():
    return {"projects": P.list_projects(), "current": P.current_project_name()}


@app.post("/api/projects")
def open_or_create(body: dict = Body(...)):
    P.set_current_project(body["name"])
    return _proj().summary()


@app.get("/api/rev")
def rev():
    return {"project": P.current_project_name(), "rev": _proj().rev}


@app.get("/api/events")
async def events():
    """Server-sent events: pushes when the active project or its revision changes (e.g. Claude edited it)."""
    async def gen():
        last = None
        n = 0
        while True:
            try:
                cur = (P.current_project_name(), _proj().rev)
            except Exception:
                cur = last
            if cur != last:
                last = cur
                yield f"data: {json.dumps({'project': cur[0], 'rev': cur[1]})}\n\n"
            n += 1
            if n % 40 == 0:  # keep-alive for reverse proxies / tunnels
                yield ": ping\n\n"
            await asyncio.sleep(0.4)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.put("/api/params")
def put_params(body: dict = Body(...)):
    proj = _proj()
    proj.set_params(body.get("params", {}), replace=bool(body.get("replace")))
    return proj.summary()


@app.put("/api/notes")
def put_notes(body: dict = Body(...)):
    proj = _proj()
    proj.data["notes"] = body.get("notes", "")
    proj.save()
    return {"ok": True}


@app.put("/api/common")
def put_common(body: dict = Body(...)):
    proj = _proj()
    proj.data["common"] = body.get("common", "")
    proj.save()
    return proj.summary()  # shared code affects every part's build status


@app.post("/api/presets")
def save_preset(body: dict = Body(...)):
    proj = _proj()
    proj.save_preset(body["name"])
    return proj.summary()


@app.post("/api/presets/{name}/apply")
def apply_preset(name: str):
    proj = _proj()
    proj.apply_preset(name)
    return proj.summary()


@app.delete("/api/presets/{name}")
def delete_preset(name: str):
    proj = _proj()
    proj.delete_preset(name)
    return proj.summary()


@app.post("/api/checkpoints")
def save_checkpoint(body: dict = Body(...)):
    proj = _proj()
    proj.save_checkpoint(body["name"])
    return proj.summary()


@app.post("/api/checkpoints/{name}/restore")
def restore_checkpoint(name: str):
    return _proj().restore_checkpoint(name)


@app.delete("/api/checkpoints/{name}")
def delete_checkpoint(name: str):
    proj = _proj()
    proj.delete_checkpoint(name)
    return proj.summary()


@app.put("/api/parts/{name}")
def put_part(name: str, body: dict = Body(...)):
    proj = _proj()
    allowed = {k: body[k] for k in ("code", "color", "filament", "visible", "export", "location", "scale", "note",
                                    "type", "plate") if k in body}
    proj.upsert_part(name, **allowed)
    if body.get("new_name") and body["new_name"] != name:
        proj.rename_part(name, body["new_name"])
    return proj.summary()


@app.delete("/api/parts/{name}")
def del_part(name: str):
    proj = _proj()
    proj.delete_part(name)
    return proj.summary()


@app.post("/api/parts/{name}/duplicate")
def dup_part(name: str):
    proj = _proj()
    spec = proj.find(name)
    new, i = f"{name}_copy", 2
    while proj.has(new):
        new, i = f"{name}_copy{i}", i + 1
    fields = {k: v for k, v in spec.items() if k != "name"}
    loc = list(fields.get("location") or [0] * 6)
    loc[0] += 10
    loc[1] += 10  # offset so the copy doesn't sit exactly on top of the original
    fields["location"] = loc
    proj.upsert_part(new, **fields)
    return {"new_name": new, **proj.summary()}


@app.post("/api/parts/{name}/array")
def array_part(name: str, body: dict = Body(default={})):
    """Duplicate a part in a grid on the bed; body: count_x, count_y, spacing_x, spacing_y, margin (all optional)."""
    proj = _proj()
    res = proj.array_part(
        name,
        count_x=body.get("count_x", 1),
        count_y=body.get("count_y", 1),
        spacing_x=body.get("spacing_x"),
        spacing_y=body.get("spacing_y"),
        margin=body.get("margin", 3.0),
    )
    return {**res, **proj.summary()}


@app.post("/api/parts/{name}/array_polar")
def array_part_polar(name: str, body: dict = Body(default={})):
    """Duplicate a part in a circle; body: count, radius, center, start_angle, rotate_copies (all optional)."""
    proj = _proj()
    res = proj.array_part_polar(
        name,
        count=body.get("count", 6),
        radius=body.get("radius"),
        center=body.get("center"),
        start_angle=body.get("start_angle", 0.0),
        rotate_copies=body.get("rotate_copies", False),
    )
    return {**res, **proj.summary()}


@app.post("/api/plates")
def add_plate():
    proj = _proj()
    proj.add_plate()
    return proj.summary()


@app.delete("/api/plates/{plate}")
def remove_plate(plate: int):
    proj = _proj()
    proj.remove_plate(plate)
    return proj.summary()


@app.post("/api/plates/arrange")
def arrange_plates(body: dict = Body(default={})):
    proj = _proj()
    res = proj.arrange_plates(body.get("names"), margin=float(body.get("margin", 5.0)))
    return {"arrange": res, **proj.summary()}


@app.post("/api/import")
async def import_file(file: UploadFile, name: str | None = None):
    """Upload STL/3MF/OBJ as a reference part. Also usable from a shell:
    curl -H "Authorization: Bearer $TOKEN" -F file=@model.stl http://host:8765/api/import"""
    proj = _proj()
    suffix = Path(file.filename or "mesh.stl").suffix or ".stl"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
    pname = P.slugify(name or Path(file.filename or "mesh").stem)
    try:
        proj.import_file(pname, tmp.name, color="#9AA5B1")
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return proj.summary()


@app.get("/api/mesh/{name}")
def mesh(name: str):
    """Binary mesh: [uint32 nverts][uint32 ntris][float32 xyz * nverts][uint32 abc * ntris]."""
    return _mesh_response(_proj().build(name))


def _mesh_response(e: dict) -> Response:
    if not e["info"].get("ok"):
        raise HTTPException(422, e["info"].get("error"))
    V, F = e["mesh"]
    head = np.array([len(V), len(F)], dtype=np.uint32).tobytes()
    data = head + V.astype(np.float32).tobytes() + F.astype(np.uint32).tobytes()
    return Response(data, media_type="application/octet-stream", headers={"Cache-Control": "no-store"})


@app.put("/api/assembly/{name}")
def put_assembly_item(name: str, body: dict = Body(...)):
    proj = _proj()
    allowed = {k: body[k] for k in ("code", "color", "visible", "ghost", "explode", "note") if k in body}
    proj.upsert_assembly_item(name, **allowed)
    return proj.summary()


@app.delete("/api/assembly/{name}")
def del_assembly_item(name: str):
    proj = _proj()
    proj.delete_assembly_item(name)
    return proj.summary()


@app.get("/api/assembly/mesh/{name}")
def assembly_mesh(name: str):
    """Same binary format as /api/mesh/{name}, for an assembly item."""
    return _mesh_response(_proj().build_assembly_item(name))


def _csv(v: str | None) -> list[str] | None:
    return [x for x in v.split(",") if x] if v is not None else None


@app.get("/api/assembly.png")
def assembly_png(view: str = "iso", hide: str | None = None, ghost: str | None = None, explode: float = 0.0,
                 section: str | None = None, section_at: float | None = None, section_flip: bool = False,
                 size: int = 1600, download: bool = False):
    """Assembly picture. hide/ghost: comma-separated item names (ghost="" = nothing see-through)."""
    proj = _proj()
    try:
        png, _ = render_assembly_png(proj, view=view, size=max(400, min(3000, size)), hide=_csv(hide),
                                     ghost=_csv(ghost), explode=explode, section=section or None,
                                     section_at=section_at, section_flip=section_flip)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    headers = {"Cache-Control": "no-store"}
    if download:
        save_assembly_png(proj, png, view)
        headers["Content-Disposition"] = f'attachment; filename="{proj.name}-assembly-{view}.png"'
    return Response(png, media_type="image/png", headers=headers)


@app.get("/api/preview.png")
def preview(view: str = "iso", overhangs: bool = False, overhang_angle: float = 45.0, plate: int | None = None):
    png, _ = render_png(_proj(), view=view, overhangs=overhangs, overhang_angle=overhang_angle, plate=plate)
    return Response(png, media_type="image/png")


@app.post("/api/export")
def export(body: dict = Body(...)):
    proj = _proj()
    fmt = body.get("format", "3mf")
    if fmt == "3mf":
        res = export_3mf(proj, mode=body.get("mode", "assembly"), flavor=body.get("flavor", "orca"),
                         thumbnail=thumbnail(proj), plate=body.get("plate"),
                         split_plates=bool(body.get("split_plates")))
        files = res["paths"] if "paths" in res else [res["path"]]
    elif fmt == "stl":
        res = export_stl(proj, separate=bool(body.get("separate", False)))
        files = res["files"]
    elif fmt == "step":
        res = export_step(proj)
        files = [res["path"]]
    else:
        raise HTTPException(400, "unknown format")
    # relative signed links: work behind any host name / proxy
    res["download"] = [u.replace(links.public_url(), "") for u in (links.download_url(f) for f in files) if u]
    return res


@app.get("/dl/{exp}/{sig}/{rel:path}")
def signed_download(exp: int, sig: str, rel: str):
    p = links.check_download(exp, sig, rel)
    if not p:
        raise HTTPException(404, "link expired or invalid")
    return FileResponse(p, filename=p.name)


def serve(host: str = "127.0.0.1", port: int = 8765, quiet: bool = False) -> None:
    import uvicorn

    P.ensure_demo()
    logging.getLogger("uvicorn.access").addFilter(_HealthLogFilter())
    uvicorn.run(app, host=host, port=port, log_level="warning" if quiet else "info", access_log=not quiet,
                proxy_headers=True, forwarded_allow_ips="*",
                # open editor tabs keep an SSE stream (/api/events) open forever; don't wait for them on shutdown
                timeout_graceful_shutdown=3)


class _HealthLogFilter(logging.Filter):
    """Drop access-log lines for the Docker healthcheck (every 30 s) so real requests stay readable."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        return not (len(args) >= 3 and str(args[2]).startswith("/health"))
