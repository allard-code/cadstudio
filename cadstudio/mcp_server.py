# SPDX-License-Identifier: GPL-3.0-or-later
"""MCP server: gives Claude (Desktop / Code / claude.ai) tools to model parts, look at them and export 3MF.

Run:  python -m cadstudio mcp      (stdio transport, e.g. for claude_desktop_config.json)
      python -m cadstudio serve    (streamable HTTP on /mcp, together with the web editor – used in Docker)
In stdio mode the web editor is started automatically in a background thread (http://127.0.0.1:8765).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import Image
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp import Image

from . import links
from . import project as P
from .export3mf import export_3mf as _export_3mf
from .export3mf import export_step as _export_step
from .export3mf import export_stl as _export_stl
from .render import render_png, thumbnail

CHEATSHEET = (Path(__file__).parent / "cheatsheet.md").read_text(encoding="utf-8")
WEB_PORT = int(os.environ.get("CADSTUDIO_PORT", "8765"))

INSTRUCTIONS = f"""CAD-Studio: parametric CAD (build123d / OpenCascade) for 3D printing, with export to
multi-colour 3MF for Orca-based slicers (Anycubic Slicer Next, OrcaSlicer, Bambu Studio) and PrusaSlicer.

Workflow:
1. get_project() to see the current state (or new_project / open_project).
2. Put dimensions in parameters (set_params) so the user can tweak them in the editor.
3. Create one part per colour / component with set_part(name, code, color, filament).
   The code is build123d and must assign `result`. Read get_build123d_reference() when unsure.
   If several parts share helper functions/constants/geometry (e.g. one profile reused by 4 colour parts),
   put that once in set_common_code() instead of repeating it in every part's code.
4. ALWAYS check visually with render_preview() and check bbox/size in the set_part response.
   Fix errors (the traceback is returned) before moving on.
5. export_3mf() for the slicer. Give the user the download_url and tell them which filament slot needs which colour.
User files (STL/3MF from MakerWorld etc.): list_inbox() + import_mesh(file_path), or import_mesh(url=...).
The server may run on another machine (Docker): paths are server paths, not paths on the user's computer.
Reply in the user's language. The user watches live in the web editor: {{web_url}}

Short API summary:
{CHEATSHEET[:2500]}
"""

mcp = _Server("cad-studio", instructions=INSTRUCTIONS.replace("{web_url}", links.public_url()))


def _proj() -> P.Project:
    return P.get_project()


def _part_report(proj: P.Project, name: str) -> dict:
    e = proj.build(name)
    spec = proj.find(name)
    return {"part": name, "color": spec["color"], "filament": spec["filament"], "visible": spec["visible"],
            **{k: v for k, v in e["info"].items() if k != "name"}}


# --------------------------------------------------------------------------- project tools

@mcp.tool()
def list_projects() -> dict:
    """List all projects and which one is active."""
    return {"projects": P.list_projects(), "current": P.current_project_name(), "home": str(P.HOME)}


@mcp.tool()
def new_project(name: str, notes: str = "") -> dict:
    """Create a new (empty) project and make it active. If it already exists it is just opened."""
    P.set_current_project(name)
    proj = _proj()
    if notes:
        proj.data["notes"] = notes
        proj.save()
    return proj.summary()


@mcp.tool()
def open_project(name: str) -> dict:
    """Open an existing project (it becomes the active project, also in the web editor)."""
    if P.slugify(name) not in P.list_projects():
        return {"error": f"Project '{name}' does not exist", "projects": P.list_projects()}
    P.set_current_project(name)
    return _proj().summary()


@mcp.tool()
def get_project() -> dict:
    """Full state of the active project: parameters, all parts with code, colour, filament slot
    and build info (ok/error, bounding box, size, volume, watertight)."""
    return _proj().summary()


@mcp.tool()
def set_notes(notes: str) -> dict:
    """Store design notes with the project (requirements, dimensions of other models, decisions)."""
    proj = _proj()
    proj.data["notes"] = notes
    proj.save()
    return {"ok": True}


@mcp.tool()
def set_common_code(code: str) -> dict:
    """build123d code executed once before every part's own code, in the same namespace (functions, constants,
    shapes reused by name). Put a helper here once instead of repeating it in every part - this is the fix for
    a multi-colour design where each part's code starts with the same block (e.g. one shared layout/profile
    used by 4 colour parts): move that block here and leave only the part-specific geometry in each part.
    Rebuilds every part (their cache key includes this code); the response is each part's new build status."""
    proj = _proj()
    proj.data["common"] = code
    proj.save()
    return {"parts": [_part_report(proj, p["name"]) for p in proj.parts]}


@mcp.tool()
def set_params(params: dict[str, Any], replace: bool = False) -> dict:
    """Set project parameters (e.g. {"w": 60, "wall": 2}). They are available as variables in all part code
    and the user can adjust them with sliders in the editor. A null value removes a parameter.
    Returns the new build status of all parts."""
    proj = _proj()
    proj.set_params(params, replace=replace)
    return {"params": proj.params, "parts": [_part_report(proj, p["name"]) for p in proj.parts]}


# --------------------------------------------------------------------------- part tools

@mcp.tool()
def save_param_preset(name: str) -> dict:
    """Save the current parameters (set_params) under a name, e.g. to switch between a "Large" and "Small"
    variant of the same parametric design without retyping every number. Overwrites a preset of the same name."""
    proj = _proj()
    proj.save_preset(name)
    return proj.summary()


@mcp.tool()
def apply_param_preset(name: str) -> dict:
    """Replace the current parameters with a saved preset (see save_param_preset); rebuilds every part."""
    proj = _proj()
    proj.apply_preset(name)
    return proj.summary()


@mcp.tool()
def delete_param_preset(name: str) -> dict:
    proj = _proj()
    proj.delete_preset(name)
    return {"presets": list(proj.presets)}


@mcp.tool()
def save_checkpoint(name: str) -> dict:
    """Snapshot the whole project (parameters, every part's code/colour/location, shared code, imported
    meshes) under a name, so you can come back to it later. Overwrites a checkpoint of the same name.
    Unlike parameter presets (which only save `set_params` values), this captures everything."""
    return _proj().save_checkpoint(name)


@mcp.tool()
def list_checkpoints() -> list[dict]:
    """List saved checkpoints (name + creation time), newest last."""
    return _proj().list_checkpoints()


@mcp.tool()
def restore_checkpoint(name: str) -> dict:
    """Replace the current project with a previously saved checkpoint (see save_checkpoint). Not undoable -
    save a checkpoint of the current state first if you might want to come back to it."""
    return _proj().restore_checkpoint(name)


@mcp.tool()
def delete_checkpoint(name: str) -> dict:
    proj = _proj()
    proj.delete_checkpoint(name)
    return {"checkpoints": proj.list_checkpoints()}


@mcp.tool()
def set_part(name: str, code: str, color: str | None = None, filament: int | None = None,
             location: list[float] | None = None, scale: list[float] | None = None, note: str | None = None) -> dict:
    """Create or replace a part from build123d code. The code must assign `result`.
    color: hex, e.g. "#D62828" (display + 3MF colour). filament: extruder / filament slot 1..8.
    location: optional [x, y, z, rx, ry, rz] applied after the code.
    scale: optional [sx, sy, sz] (default [1,1,1]) stretch/shrink about the part's own centre, applied before location.
    The response contains ok/error (+traceback), bbox, size (mm), volume, triangle count and watertight."""
    proj = _proj()
    proj.upsert_part(name, type="code", code=code, color=color, filament=filament, location=location,
                      scale=scale, note=note)
    return _part_report(proj, name)


@mcp.tool()
def update_part(name: str, color: str | None = None, filament: int | None = None, visible: bool | None = None,
                export: bool | None = None, location: list[float] | None = None, scale: list[float] | None = None,
                new_name: str | None = None) -> dict:
    """Change part properties without replacing the code (colour, slot, visibility, include in export,
    position/rotation [x,y,z,rx,ry,rz], scale [sx,sy,sz] about its own centre, rename – part("..") references
    are updated)."""
    proj = _proj()
    proj.find(name)
    proj.upsert_part(name, color=color, filament=filament, visible=visible, export=export, location=location,
                      scale=scale)
    if new_name and new_name != name:
        proj.rename_part(name, new_name)
        name = new_name
    return _part_report(proj, name)


@mcp.tool()
def add_primitive(name: str, kind: str, size: list[float], position: list[float] | None = None,
                  color: str | None = None, filament: int | None = None, text: str | None = None) -> dict:
    """Quickly add a basic shape (generates build123d code you can edit later).
    kind: box [l,w,h] | cylinder [r,h] | sphere [r] | cone [r1,r2,h] | torus [R,r] | text [font_size, depth] (+text).
    The shape sits on z=0 (bottom on the bed); position = [x,y,z] offset."""
    k = kind.lower()
    s = list(size) + [0, 0, 0]
    on_bed = "align=(Align.CENTER, Align.CENTER, Align.MIN)"
    if k == "box":
        code = f"result = Box({s[0]}, {s[1]}, {s[2]}, {on_bed})"
    elif k == "cylinder":
        code = f"result = Cylinder({s[0]}, {s[1]}, {on_bed})"
    elif k == "sphere":
        code = f"result = Pos(0, 0, {s[0]}) * Sphere({s[0]})"
    elif k == "cone":
        code = f"result = Cone({s[0]}, {s[1]}, {s[2]}, {on_bed})"
    elif k == "torus":
        code = f"result = Pos(0, 0, {s[1]}) * Torus({s[0]}, {s[1]})"
    elif k == "text":
        code = f"result = extrude(Text({json.dumps(text or name)}, font_size={s[0] or 10}), amount={s[1] or 2})"
    else:
        return {"error": f"Unknown kind '{kind}'"}
    loc = None
    if position:
        loc = (list(position) + [0, 0, 0])[:3] + [0, 0, 0]
    return set_part(name, code, color=color, filament=filament, location=loc)


@mcp.tool()
def array_part(name: str, count_x: int = 1, count_y: int = 1, spacing_x: float | None = None,
               spacing_y: float | None = None, margin: float = 3.0) -> dict:
    """Duplicate a part in a grid on the bed, e.g. to print N copies of a small part on one plate.
    spacing_x/spacing_y: centre-to-centre distance in mm; default is the part's own size + margin so copies
    don't touch. Each copy is an independent part (named "<name>_<i>_<j>"), not a reference.
    Returns the new part names and whether the whole array fits the bed."""
    return _proj().array_part(name, count_x, count_y, spacing_x, spacing_y, margin)


@mcp.tool()
def delete_part(name: str) -> dict:
    """Delete a part."""
    proj = _proj()
    proj.delete_part(name)
    return {"ok": True, "parts": [p["name"] for p in proj.parts]}


@mcp.tool()
def list_inbox() -> dict:
    """Files in the server's inbox folder (where the user drops STL/3MF/OBJ files, e.g. via the editor upload,
    a network share or a file manager). Use the name in import_mesh(file_path=...)."""
    d = links.inbox_dir()
    files = [{"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
             for f in sorted(d.iterdir()) if f.is_file() and f.suffix.lower() in (".stl", ".3mf", ".obj", ".ply", ".glb")]
    return {"inbox": str(d), "files": files}


@mcp.tool()
def import_mesh(name: str, file_path: str | None = None, url: str | None = None, color: str | None = None,
                filament: int | None = None, location: list[float] | None = None) -> dict:
    """Import an STL/3MF/OBJ as a reference part (e.g. a model from MakerWorld to design against).
    file_path: file name in the inbox (see list_inbox) or an absolute path on the server.
    url: direct download URL of the file.
    The model is centred on X/Y and placed on z=0. Mesh parts are shown, measured and exported,
    but cannot be used in booleans. Set export to false if it is only a reference."""
    proj = _proj()
    if url:
        import tempfile
        import urllib.request
        suffix = Path(url.split("?")[0]).suffix or ".stl"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CAD-Studio"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read(300 * 1024 * 1024 + 1)
        except Exception as e:
            return {"error": f"Download failed: {e}. Tip: MakerWorld/Printables require a login; ask the user to "
                             f"put the file in the inbox or upload it in the editor instead."}
        if len(data) > 300 * 1024 * 1024:
            return {"error": "file larger than 300 MB"}
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
        src = Path(tmp.name)
    elif file_path:
        src = Path(file_path)
        if not src.is_absolute():
            src = links.inbox_dir() / file_path
    else:
        return {"error": "pass file_path or url"}
    try:
        proj.import_mesh(name, src, color=color, filament=filament)
    finally:
        if url:
            src.unlink(missing_ok=True)
    if location:
        proj.upsert_part(name, location=location)
    return _part_report(proj, name)


@mcp.tool()
def measure(names: list[str] | None = None) -> dict:
    """Bounding boxes, sizes and volumes of parts (all parts if names is empty), plus the overall
    bounding box and whether it fits on the bed (250x250x250)."""
    proj = _proj()
    names = names or [p["name"] for p in proj.parts]
    reps = [_part_report(proj, n) for n in names]
    ok = [r for r in reps if r.get("ok")]
    total = None
    if ok:
        lo = [min(r["bbox_min"][i] for r in ok) for i in range(3)]
        hi = [max(r["bbox_max"][i] for r in ok) for i in range(3)]
        size = [round(hi[i] - lo[i], 3) for i in range(3)]
        total = {"bbox_min": lo, "bbox_max": hi, "size": size,
                 "fits_bed": all(size[i] <= P.BED[i] for i in range(3))}
    return {"parts": reps, "total": total}


@mcp.tool()
def render_preview(view: str = "grid", parts: list[str] | None = None, overhangs: bool = False,
                   overhang_angle: float = 45.0) -> Image:
    """Render an image of the model so you can check the result.
    view: grid (iso/front/top/right) | iso | front | back | left | right | top | bottom | iso_back.
    parts: only show these parts (default: all visible parts).
    overhangs: tint faces that need support orange (downward-facing steeper than overhang_angle degrees
    from vertical; printers can typically self-support up to ~45 deg without support material)."""
    png, errors = render_png(_proj(), view=view, parts=parts, overhangs=overhangs, overhang_angle=overhang_angle)
    if errors:
        print("render errors: " + "; ".join(errors), file=sys.stderr)
    return Image(data=png, format="png")


# --------------------------------------------------------------------------- export tools

@mcp.tool()
def export_3mf(filename: str | None = None, mode: str = "assembly", flavor: str = "orca",
               parts: list[str] | None = None, filament_density_g_cm3: float = 1.24,
               filament_price_eur_kg: float | None = None) -> dict:
    """Export to 3MF.
    mode: "assembly" = all parts as one object with one extruder/filament slot per part (multi-colour print);
          "objects"  = every part a separate object.
    flavor: "orca" (Anycubic Slicer Next, OrcaSlicer, Bambu Studio) or "prusa" (PrusaSlicer).
    filename: optional server path; default <project>/exports/<project>.3mf.
    filament_density_g_cm3: default is PLA (1.24); use ~1.27 for PETG, ~1.04 for ABS, ~1.00-1.08 for TPU.
    filament_price_eur_kg: if given, adds a rough cost estimate.
    The response contains the path, a download_url, which parts are on which filament slot, and a *rough*
    filament-weight/cost estimate per slot (solid-model volume x density - ignores infill/perimeters, so it's
    an upper bound for anything below 100% infill, which is most prints)."""
    proj = _proj()
    res = _export_3mf(proj, filename, mode=mode, flavor=flavor, only=parts, thumbnail=thumbnail(proj),
                       filament_density_g_cm3=filament_density_g_cm3, filament_price_eur_kg=filament_price_eur_kg)
    res["download_url"] = links.download_url(res["path"])
    return res


@mcp.tool()
def export_stl(filename: str | None = None, separate: bool = True, parts: list[str] | None = None) -> dict:
    """Export STL (one file per part, or merged with separate=False)."""
    res = _export_stl(_proj(), filename, only=parts, separate=separate)
    res["download_urls"] = [links.download_url(f) for f in res["files"]]
    return res


@mcp.tool()
def export_step(filename: str | None = None, parts: list[str] | None = None) -> dict:
    """Export the CAD parts as STEP (exact geometry, opens in Fusion 360 / FreeCAD / Onshape)."""
    res = _export_step(_proj(), filename, only=parts)
    res["download_url"] = links.download_url(res["path"])
    return res


# --------------------------------------------------------------------------- help / UI

@mcp.tool()
def get_build123d_reference() -> str:
    """build123d cheat sheet + printability rules + multi-colour workflow. Read this before writing complex code."""
    return CHEATSHEET


@mcp.tool()
def open_editor() -> dict:
    """Return the URL of the web editor (watch live and edit) and open it if the server runs locally."""
    url = links.public_url()
    if os.environ.get("CADSTUDIO_IN_DOCKER") != "1":
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return {"url": url}


# --------------------------------------------------------------------------- entry point

def _start_web_in_background() -> None:
    import socket

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", WEB_PORT)) == 0:
            return  # already running (e.g. started separately)
    from .web import serve

    t = threading.Thread(target=serve, kwargs={"port": WEB_PORT, "quiet": True}, daemon=True)
    t.start()


def main() -> None:
    # Protect the stdio JSON-RPC channel: anything printed to fd 1 by libraries (OCCT, fonts, user code)
    # would corrupt it. Keep a private copy of the real stdout for MCP and point fd 1 at stderr.
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = os.fdopen(real_stdout, "w", buffering=1, encoding="utf-8")

    P.ensure_demo()
    if os.environ.get("CADSTUDIO_NO_WEB") != "1":
        try:
            _start_web_in_background()
        except Exception as e:  # never let the UI break the MCP server
            print(f"web UI not started: {e}", file=sys.stderr)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
