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

import numpy as np

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import Image
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp import Image

from . import links
from . import printsettings as PS
from . import project as P
from .export3mf import export_3mf as _export_3mf
from .export3mf import export_step as _export_step
from .export3mf import export_stl as _export_stl
from .fitcheck import check_fit
from .printcheck import find_bridges, find_floating
from .render import render_assembly_png, render_png, save_assembly_png, thin_wall_mask, thumbnail

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
   Fix errors (the traceback is returned) before moving on. Before exporting, run check_floating() (parts
   that would print in mid-air - the slicer's "floating regions" warning) and check_wall_thickness(), and fix
   what they report.
5. Build plates: if the parts don't all fit on one 250x250 bed (e.g. two halves of a spool), put them on
   separate plates - set_part(..., plate=2) or arrange_plates() to spread them automatically. Parts keep
   their location relative to their own plate; the editor and export lay plates out side by side.
6. export_3mf() for the slicer (all plates in one file; split_plates=True for one file per plate).
   Give the user the download_url and tell them which filament slot needs which colour.
   Or slice_plate(plate=N) for ready-to-print G-code from the bundled OrcaSlicer (printer profile from
   CADSTUDIO_PRINTER); one_filament=True prints the whole plate from a single spool.
   send_to_printer(plate=N) then hands that G-code to Home Assistant, which starts the print (if configured).
7. Assembly: to show how the printed parts go together, add assembly items with set_assembly_item(name, code)
   (same build123d code as parts; part("x") and the shared code work) - each item in its assembled position,
   e.g. a flipped print part rotated back, or reference objects like a motor or rails. They are never exported
   or sliced. render_assembly() pictures it: ghost=[...] makes a shell see-through, section="x|y|z" cuts it
   open, explode=1 pulls it apart; export_assembly_png() gives the user a download link.
   check_assembly_fit() measures overlap and clearance between all items (too tight = jams when printed).
Before exporting also run check_bridges(): long unsupported spans sag (keep bridges under ~15-20 mm).
Print preparation: suggest_orientation() picks the side that faces the bed (least support, good base, and
strength when you give the load direction - layer lines are the weak direction); set_print_settings() stores
walls/infill/layer height chosen from what the part is for (profiles functional | strong | watertight |
decorative | draft | fine) - they go into the 3MF and slice_plate. Tell the user the orientation and settings
you chose and why.
Ready-made helpers in every part's code: spur_gear, gear_centre_distance, d_hole, d_shaft, teardrop, pin,
pin_hole, screw_boss, magnet_pocket, tolerance_coupon (see get_build123d_reference()).
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
            "plate": int(spec.get("plate", 1)),
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
             location: list[float] | None = None, scale: list[float] | None = None, note: str | None = None,
             plate: int | None = None) -> dict:
    """Create or replace a part from build123d code. The code must assign `result`.
    color: hex, e.g. "#D62828" (display + 3MF colour). filament: extruder / filament slot 1..8.
    location: optional [x, y, z, rx, ry, rz] applied after the code (relative to the part's plate centre).
    plate: build plate number (default 1; a higher number adds plates as needed) - use a separate plate for
    parts that don't fit on the bed together, instead of moving them off the bed.
    scale: optional [sx, sy, sz] (default [1,1,1]) stretch/shrink about the part's own centre, applied before location.
    The response contains ok/error (+traceback), bbox, size (mm), volume, triangle count and watertight."""
    proj = _proj()
    proj.upsert_part(name, type="code", code=code, color=color, filament=filament, location=location,
                      scale=scale, note=note, plate=plate)
    return _part_report(proj, name)


@mcp.tool()
def update_part(name: str, color: str | None = None, filament: int | None = None, visible: bool | None = None,
                export: bool | None = None, location: list[float] | None = None, scale: list[float] | None = None,
                new_name: str | None = None, plate: int | None = None) -> dict:
    """Change part properties without replacing the code (colour, slot, visibility, include in export,
    position/rotation [x,y,z,rx,ry,rz], scale [sx,sy,sz] about its own centre, build plate number, rename –
    part("..") references are updated)."""
    proj = _proj()
    proj.find(name)
    proj.upsert_part(name, color=color, filament=filament, visible=visible, export=export, location=location,
                      scale=scale, plate=plate)
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
def array_part_polar(name: str, count: int = 6, radius: float | None = None, center: list[float] | None = None,
                     start_angle: float = 0.0, rotate_copies: bool = False) -> dict:
    """Duplicate a part in a circle - a bolt-hole pattern, a ventilation grille, spoke/tooth-like shapes.
    count: total copies including the original (which keeps its current position).
    radius: distance from the centre; default is the part's own current distance from centre, or if that's
    ~0, half its own footprint diagonal plus a small margin.
    center: [x, y] of the circle; default is the part's own current XY (copies fan out around wherever the
    part already is - pass an explicit centre to array around a different point on the bed).
    rotate_copies: also rotate each copy by its angular offset around Z, for teeth/spokes that should point
    outward with the pattern rather than stay parallel to the original.
    Each copy is an independent part (named "<name>_p<i>"), not a reference."""
    return _proj().array_part_polar(name, count, radius, center, start_angle, rotate_copies)


@mcp.tool()
def delete_part(name: str) -> dict:
    """Delete a part."""
    proj = _proj()
    proj.delete_part(name)
    return {"ok": True, "parts": [p["name"] for p in proj.parts]}


@mcp.tool()
def add_plate() -> dict:
    """Add an empty build plate (bed). Put parts on it with update_part(name, plate=N)."""
    proj = _proj()
    n = proj.add_plate()
    return {"plates": n}


@mcp.tool()
def remove_plate(plate: int) -> dict:
    """Remove build plate N; its parts move to the previous plate and later plates are renumbered."""
    proj = _proj()
    n = proj.remove_plate(plate)
    return {"plates": n, "parts": {p["name"]: int(p.get("plate", 1)) for p in proj.parts}}


@mcp.tool()
def arrange_plates(names: list[str] | None = None, margin: float = 5.0) -> dict:
    """Spread the printable parts over as many build plates as needed (plates are added automatically),
    packed in rows with `margin` mm between them. Parts whose footprints overlap (a multi-colour assembly)
    move together; groups linked by part("..") references keep their position and get a plate of their own.
    names: only these parts (default: all visible, exported parts). Returns which parts are on which plate."""
    return _proj().arrange_plates(names, margin=margin)


@mcp.tool()
def list_inbox() -> dict:
    """Files in the server's inbox folder (where the user drops STL/3MF/OBJ files, e.g. via the editor upload,
    a network share or a file manager). Use the name in import_mesh(file_path=...)."""
    d = links.inbox_dir()
    files = [{"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
             for f in sorted(d.iterdir()) if f.is_file() and f.suffix.lower() in
             (".stl", ".3mf", ".obj", ".ply", ".glb", ".step", ".stp")]
    return {"inbox": str(d), "files": files}


@mcp.tool()
def import_mesh(name: str, file_path: str | None = None, url: str | None = None, color: str | None = None,
                filament: int | None = None, location: list[float] | None = None) -> dict:
    """Import a 3D file as a part.
    file_path: file name in the inbox (see list_inbox) or an absolute path on the server.
    url: direct download URL of the file.
    STEP (.step/.stp) becomes a real BRep part: usable in normal booleans with code-generated geometry
    (via part("name")) and exportable to STEP again. STL/3MF/OBJ/PLY/GLB become a reference mesh: shown,
    measured and exported, but can only be combined with other geometry via mesh_boolean(), not + - &.
    The model is centred on X/Y and placed on z=0. Set export to false if it is only a reference."""
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
        proj.import_file(name, src, color=color, filament=filament)
    finally:
        if url:
            src.unlink(missing_ok=True)
    if location:
        proj.upsert_part(name, location=location)
    return _part_report(proj, name)


@mcp.tool()
def measure(names: list[str] | None = None) -> dict:
    """Bounding boxes, sizes and volumes of parts (all parts if names is empty), plus the overall
    bounding box and whether it fits on the bed (250x250x250) - per build plate when there are several."""
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
        if proj.plate_count > 1:
            per = {}
            for k in sorted({r["plate"] for r in ok}):
                on = [r for r in ok if r["plate"] == k]
                sz = [round(max(r["bbox_max"][i] for r in on) - min(r["bbox_min"][i] for r in on), 3) for i in range(3)]
                per[str(k)] = {"parts": [r["part"] for r in on], "size": sz,
                               "fits_bed": all(sz[i] <= P.BED[i] for i in range(3))}
            total["plates"] = per
            total["fits_bed"] = all(v["fits_bed"] for v in per.values())
    return {"parts": reps, "total": total}


@mcp.tool()
def check_wall_thickness(names: list[str] | None = None, threshold_mm: float = 1.2) -> dict:
    """Find walls thinner than threshold_mm (default 1.2 mm = about 3 perimeter lines at a 0.4 mm nozzle) -
    a wall that thin, or thinner, is likely to print weak or not at all. Works by casting a ray from each
    face into the solid to the first opposite wall; a heuristic, not exact, and needs a reasonably
    watertight mesh (same caveat as mesh_boolean()).
    names: parts to check (default: all parts that build ok).
    Returns, per part: the thinnest point found (min_thickness_mm), how many faces are below the threshold,
    and the world-space location of the thinnest point (pass it as the centre of a render_preview, or just
    look at that area of the model)."""
    proj = _proj()
    names = names or [p["name"] for p in proj.parts]
    reports = []
    for n in names:
        e = proj.build(n)
        if not e["info"].get("ok"):
            reports.append({"part": n, "ok": False, "error": e["info"].get("error")})
            continue
        if not e.get("mesh"):
            reports.append({"part": n, "ok": False, "error": "part has no mesh to check"})
            continue
        V, F = e["mesh"]
        thickness, thin = thin_wall_mask(V, F, threshold_mm)
        finite = thickness[np.isfinite(thickness)]
        if not len(finite):
            reports.append({"part": n, "ok": True, "min_thickness_mm": None, "thin_faces": 0, "total_faces": len(F)})
            continue
        worst = int(np.argmin(thickness))
        point = V[F[worst]].mean(axis=0).round(2).tolist()
        reports.append({"part": n, "ok": True, "min_thickness_mm": round(float(finite.min()), 3),
                        "thin_faces": int(thin.sum()), "total_faces": len(F), "worst_point": point})
    return {"threshold_mm": threshold_mm, "parts": reports}


@mcp.tool()
def check_floating(plate: int | None = None, layer_height_mm: float = 0.2, pitch_mm: float = 0.2,
                   min_area_mm2: float = 0.1) -> dict:
    """Find "floating regions": areas that would be printed in mid-air because nothing is below them in the
    previous layer - the slicer's "floating regions" warning. Typical causes: a feature that starts inside a
    hollow body (a chimney cylinder poking below a ceiling), a sphere/cone tip hanging into a cavity, or a part
    that doesn't touch the bed. Overhangs and bridges that are attached to already printed material are NOT
    reported (use render_preview(overhangs=True) for those). Run this after designing, before export_3mf.
    Slices every exported part like a slicer (layer_height_mm, rasterised at pitch_mm), per build plate; parts on
    the same plate support each other (inlays/multi-colour are fine). plate: only that plate (default: all).
    Returns per plate a list of islands {part, z_mm, area_mm2, center [x, y], bbox} (plate coordinates),
    lowest first; an empty list means the plate prints without floating regions."""
    by_plate, skipped = _plate_meshes(_proj(), plate)
    plates = {}
    for k in sorted(by_plate):
        islands = find_floating(by_plate[k], layer_height=layer_height_mm, pitch=pitch_mm, min_area_mm2=min_area_mm2)
        plates[str(k)] = {"parts": [n for n, _, _ in by_plate[k]], "floating": islands, "ok": not islands}
    res: dict[str, Any] = {"layer_height_mm": layer_height_mm, "plates": plates,
                           "ok": all(v["ok"] for v in plates.values())}
    if skipped:
        res["skipped"] = skipped
    return res


def _plate_meshes(proj: P.Project, plate: int | None):
    by_plate: dict[int, list] = {}
    skipped = []
    for p in proj.parts:
        s = {**P.PART_DEFAULTS, **p}
        if not s["export"] or (plate is not None and int(s["plate"]) != int(plate)):
            continue
        e = proj.build(s["name"])
        if not e["info"].get("ok") or not e.get("mesh"):
            skipped.append({"part": s["name"], "error": e["info"].get("error", "no mesh")})
            continue
        V, F = e["mesh"]
        by_plate.setdefault(int(s["plate"]), []).append((s["name"], V, F))
    return by_plate, skipped


@mcp.tool()
def check_bridges(plate: int | None = None, max_bridge_mm: float = 20.0, max_overhang_mm: float = 1.0,
                  layer_height_mm: float = 0.2, pitch_mm: float = 0.2) -> dict:
    """Find long bridges and overhangs - spans printed over air, attached at the ends (a ceiling, the top of a
    window) or at one side (a ledge). Long spans sag and string: on a typical printer bridges up to ~15 mm are
    clean, 15-25 mm sag a little, longer ones need a different shape (45-degree chamfers that narrow the flat
    part, a support rib, or printing the part another way up). 45-degree slopes count as supported.
    Slices every exported part like a slicer, per build plate. Returns per plate the longest bridge per part
    and the issues {part, kind: bridge|overhang, span_mm, z_mm, area_mm2, center, bbox} beyond the limits.
    Floating regions (no support at all) are reported by check_floating instead."""
    by_plate, skipped = _plate_meshes(_proj(), plate)
    plates = {}
    for k in sorted(by_plate):
        r = find_bridges(by_plate[k], layer_height=layer_height_mm, pitch=pitch_mm, max_bridge_mm=max_bridge_mm,
                         max_overhang_mm=max_overhang_mm)
        plates[str(k)] = {"parts": [n for n, _, _ in by_plate[k]], **r, "ok": not r["issues"]}
    res: dict[str, Any] = {"max_bridge_mm": max_bridge_mm, "max_overhang_mm": max_overhang_mm, "plates": plates,
                           "ok": all(v["ok"] for v in plates.values())}
    if skipped:
        res["skipped"] = skipped
    return res


@mcp.tool()
def suggest_orientation(plate: int | None = None, parts: list[str] | None = None,
                        load_direction: str | list[float] | None = None, overhang_angle: float = 45.0,
                        apply: int | None = None, count: int = 3) -> dict:
    """Find the best way up to print: which side faces the bed. The parts are treated as ONE rigid group
    (default: all exported parts on `plate`, default plate 1 - so a multi-colour inlay turns with its body;
    or the given `parts`). Candidates: the current orientation, the six axis directions and the largest flat
    faces. Each is scored on support area (downward faces steeper than overhang_angle, not on the bed), bed
    contact (flat base: adhesion, no tipping), height, and - if load_direction is given - strength: printed
    parts split along the layer lines, so a load that pulls the layers apart is the weakest case.
    load_direction: the main load in the current model frame, "x" | "y" | "z" or a vector (e.g. a hook pulled
    along its length -> that axis); ask yourself how the part is used before choosing.
    apply: rank number of a candidate to apply (rotates the group about its centre and puts it back on the
    bed; the part code is untouched, only location changes). Without apply nothing changes.
    Returns current metrics and the best `count` candidates {rank, label, rotation_deg, support_area_mm2,
    support_pct_of_surface, bed_contact_mm2, height_mm, footprint_mm, load_across_layers, score (lower =
    better)}. After applying: render_preview, check_floating and check_bridges again (a new floor can create
    new bridges), and set_print_settings(supports=True) if the chosen side still needs support."""
    from . import orient as O
    proj = _proj()
    try:
        if parts:
            names = [proj.find(n)["name"] for n in parts]
        else:
            k = int(plate or 1)
            names = [p["name"] for p in proj.parts if {**P.PART_DEFAULTS, **p}["export"]
                     and int(p.get("plate", 1)) == k]
            if not names:
                return {"ok": False, "error": f"No exported parts on plate {k}"}
        Vs, Fs, off = [], [], 0
        for n in names:
            e = proj.build(n)
            if not e["info"].get("ok"):
                return {"ok": False, "error": f"Part '{n}' fails to build: {e['info'].get('error')}"}
            V, F = e["mesh"]
            Vs.append(V)
            Fs.append(F + off)
            off += len(V)
        res = O.suggest(np.vstack(Vs), np.vstack(Fs), overhang_angle=overhang_angle, load=load_direction,
                        count=max(1, int(count)))
    except (P.PartError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    out: dict[str, Any] = {"ok": True, "parts": names, "current": res["current"],
                           "candidates": [{k: v for k, v in r.items() if k != "_R"} for r in res["candidates"]]}
    if apply is not None:
        pick = next((r for r in res["all"] if r["rank"] == int(apply)), None)
        if pick is None:
            return {**out, "ok": False, "error": f"No candidate with rank {apply}"}
        out["applied"] = {"rank": pick["rank"], "label": pick["label"],
                          "locations": proj.rotate_parts(names, pick["_R"])}
        out["next"] = "render_preview(), check_floating() and check_bridges() to confirm the new orientation"
    return out


@mcp.tool()
def check_assembly_fit(items: list[str] | None = None, allow: list[list[str]] | None = None,
                       min_clearance: float = 0.3) -> dict:
    """Check how the assembly fits together: for every pair of assembly items that come close, the overlap
    (mm3, the solids intersect - they can't both be there) or the smallest gap. A gap below min_clearance
    (default 0.3 mm) usually closes up when printed: the parts jam. Pairs that are meant to touch or press
    (a pin in its hole, a part resting on another) go in allow, e.g. [["leg*", "deck"], ["kap", "deck"]]
    (* wildcards). Returns ok, issues (overlap / touch / tight, worst first) and all measured pairs.
    Split an assembly into one item per physical component so every fit gets checked."""
    return check_fit(_proj(), items=items, allow=allow, min_clearance=min_clearance)


@mcp.tool()
def render_preview(view: str = "grid", parts: list[str] | None = None, overhangs: bool = False,
                   overhang_angle: float = 45.0, plate: int | None = None) -> Image:
    """Render an image of the model so you can check the result.
    view: grid (iso/front/top/right) | iso | front | back | left | right | top | bottom | iso_back.
    parts: only show these parts (default: all visible parts).
    overhangs: tint faces that need support orange (downward-facing steeper than overhang_angle degrees
    from vertical; printers can typically self-support up to ~45 deg without support material).
    plate: only that build plate (default: all plates side by side)."""
    png, errors = render_png(_proj(), view=view, parts=parts, overhangs=overhangs, overhang_angle=overhang_angle,
                             plate=plate)
    if errors:
        print("render errors: " + "; ".join(errors), file=sys.stderr)
    return Image(data=png, format="png")


# --------------------------------------------------------------------------- assembly tools

def _assembly_report(proj: P.Project, name: str) -> dict:
    e = proj.build_assembly_item(name)
    spec = proj.find_assembly_item(name)
    return {"item": name, "color": spec["color"], "visible": spec["visible"], "ghost": spec["ghost"],
            "explode": spec["explode"], **{k: v for k, v in e["info"].items() if k != "name"}}


@mcp.tool()
def set_assembly_item(name: str, code: str | None = None, color: str | None = None, visible: bool | None = None,
                      ghost: bool | None = None, explode: list[float] | None = None, note: str | None = None) -> dict:
    """Create or change an item of the project's assembly: how the printed parts go together, for pictures
    (render_assembly) and fit checks - never exported or sliced, not on a build plate.
    code: build123d code assigning `result` in the ASSEMBLED position (z=0 = the ground / rail top), like a
    part's code: shared code, parameters and part("name") work (e.g. `result = Pos(0, 0, 25) * Rot(180, 0, 0) *
    part("deck")` to turn a part printed upside down back over). Use one item per colour / component, also for
    reference objects that aren't printed (motor, battery, rails). Omit code to change only the other fields.
    ghost: draw it see-through by default (e.g. the body shell). explode: [dx, dy, dz] mm direction for the
    exploded view at explode=1 (default: away from the assembly centre); [] resets it."""
    proj = _proj()
    fields = {"code": code, "color": color, "visible": visible, "ghost": ghost, "note": note}
    if explode is not None:
        fields["explode"] = explode
    if code is None:
        proj.find_assembly_item(name)  # only changing properties: the item must exist
    proj.upsert_assembly_item(name, **fields)
    return _assembly_report(proj, name)


@mcp.tool()
def delete_assembly_item(name: str) -> dict:
    """Remove an item from the assembly."""
    proj = _proj()
    proj.delete_assembly_item(name)
    return {"deleted": name, "assembly": [a["name"] for a in proj.assembly]}


@mcp.tool()
def render_assembly(view: str = "iso", items: list[str] | None = None, hide: list[str] | None = None,
                    ghost: list[str] | None = None, explode: float = 0.0, section: str | None = None,
                    section_at: float | None = None, section_flip: bool = False) -> Image:
    """Render the assembly (see set_assembly_item) so you and the user can see how everything goes together.
    view: grid | iso | front | back | left | right | top | bottom | iso_back.
    items: only these items; hide: leave these out (default: all visible items).
    ghost: items drawn see-through, e.g. ["kap"] to look inside the body (default: items marked ghost; [] = none).
    explode: 0 = assembled; 1 = every item twice as far from the centre (or along its explode vector).
    section: "x" | "y" | "z" cuts everything at section_at mm (default: the middle) and removes the half facing
    the viewer (section_flip=True: the other half); cut faces are red."""
    png, errors = render_assembly_png(_proj(), view=view, items=items, hide=hide, ghost=ghost, explode=explode,
                                      section=section, section_at=section_at, section_flip=section_flip)
    if errors:
        print("render errors: " + "; ".join(errors), file=sys.stderr)
    return Image(data=png, format="png")


@mcp.tool()
def export_assembly_png(view: str = "iso", items: list[str] | None = None, hide: list[str] | None = None,
                        ghost: list[str] | None = None, explode: float = 0.0, section: str | None = None,
                        section_at: float | None = None, section_flip: bool = False, size: int = 1600,
                        filename: str | None = None) -> dict:
    """Same picture as render_assembly(), saved as a PNG (default <project>/exports/<project>-assembly-<view>.png)
    with a download_url to give to the user. size: image width in pixels (400-3000)."""
    proj = _proj()
    png, errors = render_assembly_png(proj, view=view, size=max(400, min(3000, int(size))), items=items, hide=hide,
                                      ghost=ghost, explode=explode, section=section, section_at=section_at,
                                      section_flip=section_flip)
    path = save_assembly_png(proj, png, view, filename)
    return {"path": str(path), "download_url": links.download_url(path), "errors": errors}


# --------------------------------------------------------------------------- export tools

@mcp.tool()
def export_3mf(filename: str | None = None, mode: str = "assembly", flavor: str = "orca",
               parts: list[str] | None = None, filament_density_g_cm3: float = 1.24,
               filament_price_eur_kg: float | None = None, print_rate_cm3_per_hour: float | None = 15.0,
               plate: int | None = None, split_plates: bool = False) -> dict:
    """Export to 3MF.
    Build plates: by default every plate goes into one file (orca flavour: real slicer plates, each plate's
    parts centred on it). plate=N exports only that plate; split_plates=True writes one file per plate
    (response: paths + download_urls).
    mode: "assembly" = all parts as one object with one extruder/filament slot per part (multi-colour print);
          "objects"  = every part a separate object.
    flavor: "orca" (Anycubic Slicer Next, OrcaSlicer, Bambu Studio) or "prusa" (PrusaSlicer).
    filename: optional server path; default <project>/exports/<project>.3mf.
    filament_density_g_cm3: default is PLA (1.24); use ~1.27 for PETG, ~1.04 for ABS, ~1.00-1.08 for TPU.
    filament_price_eur_kg: if given, adds a rough cost estimate.
    print_rate_cm3_per_hour: used for a rough print-time estimate (default 15, typical for a 0.4mm nozzle at
    ~0.2mm layers); pass None to skip it, or your own figure if you know the printer runs faster/slower.
    The response contains the path, a download_url, which parts are on which filament slot, and *rough*
    filament-weight/cost/time estimates (solid-model volume x density - ignores infill/perimeters, so these
    are upper bounds for anything below 100% infill, which is most prints; the slicer's own estimate, once
    you've actually sliced with your real settings, will be more accurate and is usually lower)."""
    proj = _proj()
    res = _export_3mf(proj, filename, mode=mode, flavor=flavor, only=parts, thumbnail=thumbnail(proj),
                       filament_density_g_cm3=filament_density_g_cm3, filament_price_eur_kg=filament_price_eur_kg,
                       print_rate_cm3_per_hour=print_rate_cm3_per_hour, plate=plate, split_plates=split_plates)
    if "paths" in res:
        res["download_urls"] = [links.download_url(p) for p in res["paths"]]
    else:
        res["download_url"] = links.download_url(res["path"])
    return res


@mcp.tool()
def set_print_settings(part: str | None = None, profile: str | None = None, layer_height_mm: float | None = None,
                       wall_loops: int | None = None, top_layers: int | None = None, bottom_layers: int | None = None,
                       infill_percent: float | None = None, infill_pattern: str | None = None,
                       supports: bool | None = None, support_type: str | None = None,
                       brim_width_mm: float | None = None, clear: bool = False) -> dict:
    """Store print settings with the design. They are written into every exported 3MF as per-object / per-part
    settings (the slicer opens the file with them applied) and slice_plate uses them. Choose them from what the
    part is FOR - load, wear, watertightness, looks - and say why in one line to the user.
    part=None: settings for the whole project (every object); part="name": settings for one part only (e.g. a
    strong body with a decorative inlay) - per part only walls, top/bottom layers and infill are possible.
    profile: functional (brackets, holders, clips: 4 walls, 30% gyroid) | strong (load-bearing, hinges: 6 walls,
    50% gyroid) | watertight (ducts, containers: 5 walls, extra top/bottom) | decorative (2 walls, 10%) |
    draft (0.28 mm fit test) | fine (0.12 mm detail) | standard (slicer defaults); "" removes the profile.
    Other arguments override single values on top of the profile: infill_pattern e.g. gyroid | grid | cubic |
    honeycomb | lightning | rectilinear | concentric; support_type normal | tree. Values you leave out stay as
    stored; clear=True starts from scratch. Call with no arguments to read the current settings.
    Layer lines are the weak direction: also check the orientation (suggest_orientation) for loaded parts.
    Returns the stored settings and the effective settings per level."""
    proj = _proj()
    overrides = {"layer_height_mm": layer_height_mm, "wall_loops": wall_loops, "top_layers": top_layers,
                 "bottom_layers": bottom_layers, "infill_percent": infill_percent, "infill_pattern": infill_pattern,
                 "supports": supports, "support_type": support_type, "brim_width_mm": brim_width_mm}
    try:
        if profile is not None or clear or any(v is not None for v in overrides.values()):
            proj.set_print_settings(part=part, profile=profile, overrides=overrides, clear=clear)
        elif part is not None:
            proj.find(part)
    except (PS.PrintSettingsError, P.PartError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, **_print_settings_report(proj)}


def _print_settings_report(proj: P.Project) -> dict:
    parts = {}
    for p in proj.parts:
        if p.get("print"):
            parts[p["name"]] = {"stored": p["print"], "effective": PS.part_settings(p)}
    return {"project": {"stored": proj.data.get("print", {}), "effective": PS.project_settings(proj.data)},
            "parts": parts, "profiles": PS.PROFILE_HELP}


@mcp.tool()
def slice_plate(plate: int = 1, materials: list[str] | None = None, one_filament: bool = False,
                layer_height_mm: float | None = None, infill_percent: float | None = None,
                wall_loops: int | None = None, top_layers: int | None = None, bottom_layers: int | None = None,
                supports: bool | None = None, brim_width_mm: float | None = None, process: str | None = None,
                printer: str | None = None, infill_pattern: str | None = None,
                support_type: str | None = None) -> dict:
    """Slice one build plate to G-code with the bundled OrcaSlicer (Docker image), ready for the printer.
    Uses OrcaSlicer's system profiles for the printer (default from CADSTUDIO_PRINTER, e.g.
    "Anycubic Kobra S1 0.4 nozzle") and its default process ("0.20mm Standard @..."), then the project's print
    settings (set_print_settings: profile + overrides, and per-part settings), then the overrides given here
    for this slice only: layer_height_mm, infill_percent, infill_pattern, wall_loops, top_layers,
    bottom_layers, supports, support_type, brim_width_mm.
    materials: one entry per filament slot used on the plate, in slot order - a material ("PLA", "PETG",
    "PLA+", "ABS", ...) or a full OrcaSlicer filament preset name. Default: PLA for every slot.
    one_filament=True prints all parts with a single filament (filament 1 in the G-code); which ACE/AMS slot
    feeds it is chosen when the print is started (in the slicer/printer app or by the print service).
    Returns the G-code path + download_url, the print settings used and the slicer's own estimates (print
    time, filament grams) - check them before send_to_printer and adjust if the print is too long/heavy."""
    from . import slicer
    proj = _proj()
    if not slicer.available():
        return {"ok": False, "error": "OrcaSlicer is not available on this server. It is bundled in the Docker "
                                      "image (ghcr.io/allard-code/cadstudio); a local install needs CADSTUDIO_ORCA."}
    try:
        slots = sorted({int(s["filament"]) for s, _, _ in P.exportable_meshes(proj, None, plate=plate)})
        here = PS.normalize({"layer_height_mm": layer_height_mm, "infill_percent": infill_percent,
                             "infill_pattern": infill_pattern, "wall_loops": wall_loops, "top_layers": top_layers,
                             "bottom_layers": bottom_layers, "supports": supports, "support_type": support_type,
                             "brim_width_mm": brim_width_mm})
    except (P.PartError, PS.PrintSettingsError) as e:
        return {"ok": False, "error": str(e)}
    settings = {**PS.project_settings(proj.data), **here}
    fmap = {k: (1 if one_filament else i + 1) for i, k in enumerate(slots)}
    n = 1 if one_filament else len(slots)
    mats = list(materials or [])
    if len(mats) < n:
        mats += [mats[-1] if mats else "PLA"] * (n - len(mats))
    mats = mats[:n]
    out_dir = proj.dir / "exports"
    model = out_dir / f"{proj.name}-plate{plate}.3mf"
    try:
        exp = _export_3mf(proj, model, mode="assembly", flavor="orca", plate=plate, filament_map=fmap,
                          print_settings=settings)
        res = slicer.slice_3mf(model, out_dir, printer=printer or slicer.DEFAULT_PRINTER, process=process,
                               filaments=mats, settings=PS.to_orca(settings))
    except slicer.SlicerError as e:
        return {"ok": False, "error": str(e)}
    res.pop("log", None)
    res.update({"ok": True, "plate": plate, "download_url": links.download_url(res["gcode"]),
                "print_settings": exp.get("print_settings", {"object": settings, "parts": {}}),
                "filament_slots_in_gcode": {str(fmap[k]): f"CAD-Studio slot {k}" for k in slots}
                if not one_filament else {"1": f"all parts (CAD-Studio slots {slots})"}})
    return res


@mcp.tool()
def send_to_printer(plate: int = 1) -> dict:
    """Hand the G-code of a plate (made by slice_plate) to Home Assistant, which starts the print.
    Uploads the G-code to Home Assistant (/api/file_upload) and fires the event CADSTUDIO_HA_EVENT
    (default "cadstudio_print_request") with: file_id, filename, project, plate, material, materials,
    print_time, filament_g. A Home Assistant automation listens for that event - typically it asks on the
    user's phone which ACE/AMS slot to print from and then calls the printer integration's print action with
    uploaded_gcode_file = file_id. Needs CADSTUDIO_HA_URL and CADSTUDIO_HA_TOKEN (admin user) on the server.
    Run slice_plate(plate=N) first; this sends the most recent slice of that plate."""
    from . import homeassistant as HA
    from . import slicer
    if not HA.configured():
        return {"ok": False, "error": "Home Assistant is not configured on this server: set CADSTUDIO_HA_URL and "
                                      "CADSTUDIO_HA_TOKEN (long-lived token of an admin user) and restart."}
    proj = _proj()
    gcode = proj.dir / "exports" / f"{proj.name}-plate{plate}.gcode"
    if not gcode.is_file():
        return {"ok": False, "error": f"No G-code for plate {plate} yet - run slice_plate(plate={plate}) first."}
    warnings = []
    pj = proj.dir / "project.json"
    if pj.exists() and pj.stat().st_mtime > gcode.stat().st_mtime + 1:
        warnings.append("The project was changed after this plate was sliced; the G-code may be outdated "
                        "(run slice_plate again if the parts on this plate changed).")
    stats = slicer._parse_gcode_stats(gcode)
    materials = HA.gcode_materials(gcode)
    try:
        file_id = HA.upload_file(gcode)
        data = {"file_id": file_id, "filename": gcode.name, "project": proj.name, "plate": plate,
                "material": materials[0] if materials else "", "materials": materials,
                "print_time": stats.get("print_time", ""), "filament_g": stats.get("filament_g", "")}
        event = HA.fire_event(data)
    except HA.HomeAssistantError as e:
        return {"ok": False, "error": str(e)}
    res = {"ok": True, "event": event, **data}
    if warnings:
        res["warnings"] = warnings
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
