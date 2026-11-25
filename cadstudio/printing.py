# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice a build plate and hand it to the printer - shared by the MCP tools and the editor's REST API.

Pauses: a part's code can set `pause_at = [z, ...]` (mm above the bed) and slice_plate(pauses=[...]) adds more.
The printer then pauses before printing the first layer above each height - e.g. to drop a magnet or a nut into
a closed cavity - with the printer profile's own pause command (OrcaSlicer `machine_pause_gcode`).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import links
from . import printsettings as PS
from . import project as P
from .export3mf import export_3mf as _export_3mf

LAYER_RE = re.compile(r"^;\s*Z\s*:\s*([0-9.]+)\s*$")


def insert_pauses(gcode: Path, heights: list[float], pause_gcode: str) -> list[dict]:
    """Insert pause_gcode before the first layer whose top is above each height (OrcaSlicer marks every layer
    with ';LAYER_CHANGE' followed by ';Z:<top>'). Returns [{at_mm, layer_z_mm, layer}] per inserted pause."""
    heights = sorted({round(float(h), 3) for h in heights})
    if not heights:
        return []
    lines = gcode.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    out, done, todo, layer = [], [], list(heights), 0
    cmd = pause_gcode.strip() or "M601"
    i = 0
    while i < len(lines):
        ln = lines[i]
        out.append(ln)
        if ln.startswith(";LAYER_CHANGE") and i + 1 < len(lines):
            m = LAYER_RE.match(lines[i + 1].strip())
            if m:
                layer += 1
                z = float(m.group(1))
                hit = [h for h in todo if z > h + 1e-3]
                if hit and layer > 1:
                    out.append(lines[i + 1])
                    i += 1
                    out.append(f"; CAD-Studio pause before layer {layer} (Z {z:g}) for "
                               f"{', '.join(f'{h:g}' for h in hit)} mm\n{cmd}\n")
                    done.append({"at_mm": hit[0] if len(hit) == 1 else hit, "layer_z_mm": z, "layer": layer})
                    todo = [h for h in todo if h not in hit]
        i += 1
    gcode.write_text("".join(out), encoding="utf-8")
    return done


def plate_pauses(proj: P.Project, plate: int) -> list[float]:
    """pause_at heights of every exported part on a plate (plate coordinates)."""
    hs: set[float] = set()
    for p in proj.parts:
        s = {**P.PART_DEFAULTS, **p}
        if not s["export"] or int(s["plate"]) != int(plate):
            continue
        e = proj.build(s["name"])
        hs.update(e["info"].get("pause_at") or [])
    return sorted(hs)


def slice_plate(proj: P.Project, plate: int = 1, materials: list[str] | None = None, one_filament: bool = False,
                overrides: dict | None = None, process: str | None = None, printer: str | None = None,
                pauses: list[float] | None = None) -> dict[str, Any]:
    from . import slicer

    if not slicer.available():
        return {"ok": False, "error": "OrcaSlicer is not available on this server. It is bundled in the Docker "
                                      "image (ghcr.io/allard-code/cadstudio); a local install needs CADSTUDIO_ORCA."}
    try:
        slots = sorted({int(s["filament"]) for s, _, _ in P.exportable_meshes(proj, None, plate=plate)})
        here = PS.normalize(overrides)  # this slice only, on top of the project's print settings
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
    printer = printer or slicer.DEFAULT_PRINTER
    try:
        # pauses=False: slice_plate inserts its own pauses below, at the exact layer of the sliced G-code
        exp = _export_3mf(proj, model, mode="assembly", flavor="orca", plate=plate, filament_map=fmap,
                          print_settings=settings, pauses=False)
        res = slicer.slice_3mf(model, out_dir, printer=printer, process=process, filaments=mats,
                               settings=PS.to_orca(settings))
    except slicer.SlicerError as e:
        return {"ok": False, "error": str(e)}
    res.pop("log", None)
    heights = sorted(set(plate_pauses(proj, plate)) | {float(h) for h in (pauses or [])})
    if heights:
        try:
            pause_cmd = slicer.flatten("machine", printer).get("machine_pause_gcode") or "M601"
        except Exception:  # noqa: BLE001 - profile lookup is best effort
            pause_cmd = "M601"
        res["pauses"] = insert_pauses(Path(res["gcode"]), heights, pause_cmd)
        missed = [h for h in heights if not any(h in (d["at_mm"] if isinstance(d["at_mm"], list) else [d["at_mm"]])
                                                for d in res["pauses"])]
        if missed:
            res["warnings"] = [f"No layer above {', '.join(f'{h:g}' for h in missed)} mm: those pauses were skipped"]
    res.update({"ok": True, "plate": plate, "download_url": links.download_url(res["gcode"]),
                "print_settings": exp.get("print_settings", {"object": settings, "parts": {}}),
                "filament_slots_in_gcode": {str(fmap[k]): f"CAD-Studio slot {k}" for k in slots}
                if not one_filament else {"1": f"all parts (CAD-Studio slots {slots})"}})
    return res


def send_plate(proj: P.Project, plate: int = 1) -> dict[str, Any]:
    from . import homeassistant as HA
    from . import slicer

    if not HA.configured():
        return {"ok": False, "error": "Home Assistant is not configured on this server: set CADSTUDIO_HA_URL and "
                                      "CADSTUDIO_HA_TOKEN (long-lived token of an admin user) and restart."}
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


def last_slice(proj: P.Project, plate: int) -> dict[str, Any] | None:
    """Estimates of the most recent slice of a plate, and whether the project changed since."""
    from . import slicer

    gcode = proj.dir / "exports" / f"{proj.name}-plate{plate}.gcode"
    if not gcode.is_file():
        return None
    pj = proj.dir / "project.json"
    stats = slicer._parse_gcode_stats(gcode)
    return {"plate": plate, **stats, "pauses": len(re.findall(r"^; CAD-Studio pause", gcode.read_text(
        encoding="utf-8", errors="replace"), re.M)),
            "outdated": bool(pj.exists() and pj.stat().st_mtime > gcode.stat().st_mtime + 1),
            "download_url": links.download_url(gcode)}
