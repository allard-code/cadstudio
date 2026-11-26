# SPDX-License-Identifier: GPL-3.0-or-later
"""3MF / STL export with per-part colour and filament (extruder) assignment.

Two flavours:
  * "orca"  – Bambu Studio / OrcaSlicer / Anycubic Slicer Next layout: one object made of several
              component meshes ("parts"), with Metadata/model_settings.config giving every part its
              extruder (= ACE Pro slot). This keeps multi-colour parts aligned as one printable object.
  * "prusa" – PrusaSlicer/SuperSlicer layout: one mesh object, volumes defined by triangle ranges in
              Metadata/Slic3r_PE_model.config.
Both also write core-spec <basematerials> colours so generic viewers (Windows 3D Viewer etc.) show colours.

mode="assembly" puts all parts in one object (multi-colour print);
mode="objects"  writes each part as its own object (several separate prints on one plate).

Build plates: every part has a plate number. In the orca flavour all plates go into one file - objects are
placed in the slicer's plate grid (same layout rule as Orca/Bambu) and Metadata/model_settings.config gets a
<plate> block per plate listing its objects. Orca / Bambu Studio / Anycubic Slicer Next only rebuild those
plates when the file also carries a full project config (printer + process + filament presets), which
CAD-Studio does not write: they import it as geometry, keep one plate and leave plates 2+ beside the bed.
split_plates=True (one 3MF per plate) or plate=N (one plate, centred on the bed) is what those slicers open
correctly; the one-file layout is kept for tools that read the plate blocks themselves.
"""
from __future__ import annotations

import datetime as _dt
import math
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from . import printsettings as PS
from .project import BED, PartError, Project, exportable_meshes, mesh_volume, plate_origin, slugify

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="text/xml"/>
 <Default Extension="xml" ContentType="text/xml"/>
 <Default Extension="png" ContentType="image/png"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/Metadata/thumbnail.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
</Relationships>"""

IDENTITY = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


def _fmt(x: float) -> str:
    s = f"{x:.5f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _mesh_xml(V: np.ndarray, F: np.ndarray) -> str:
    vs = "\n".join(f'     <vertex x="{_fmt(a)}" y="{_fmt(b)}" z="{_fmt(c)}"/>' for a, b, c in V)
    ts = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in F)
    return f"   <mesh>\n    <vertices>\n{vs}\n    </vertices>\n    <triangles>\n{ts}\n    </triangles>\n   </mesh>"


def _color(c: str) -> str:
    c = (c or "#CCCCCC").strip()
    if not c.startswith("#"):
        c = "#" + c
    return (c.upper() + "FF") if len(c) == 7 else c.upper()


def _place(items, center: bool, offset: tuple[float, float] = (0.0, 0.0), label: str = "Model"):
    """Translate all meshes together so the group sits on the bed (z=0) and is centred on the plate,
    then shift by `offset` (the plate's position in the slicer's plate grid)."""
    allv = np.vstack([V for _, V, _ in items])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    size = hi - lo
    if center:
        shift = np.array([BED[0] / 2 - (lo[0] + hi[0]) / 2, BED[1] / 2 - (lo[1] + hi[1]) / 2, -lo[2]])
    else:
        shift = np.array([0.0, 0.0, -lo[2]])
    shift = shift + np.array([offset[0], offset[1], 0.0])
    warn = []
    if size[0] > BED[0] or size[1] > BED[1] or size[2] > BED[2]:
        warn.append(f"{label} ({size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm) is larger than the bed {BED}"
                    f" - spread the parts over more plates (arrange_plates)")
    return [(s, V + shift, F) for s, V, F in items], warn


def _place_plates(items, count: int):
    """Centre each plate's parts on its own plate and move it to that plate's spot in the plate grid.
    Returns (placed items in input order, warnings, sorted list of plate numbers in use)."""
    by_plate: dict[int, list] = {}
    for it in items:
        by_plate.setdefault(int(it[0]["plate"]), []).append(it)
    placed, warnings = {}, []
    for k, grp in by_plate.items():
        pts, w = _place(grp, center=True, offset=plate_origin(k, count),
                        label=f"Plate {k}" if count > 1 else "Model")
        warnings += w
        for (s, V, F) in pts:
            placed[s["name"]] = (s, V, F)
    return [placed[s["name"]] for s, _, _ in items], warnings, sorted(by_plate)


def _settings_xml(settings: dict[str, str], indent: str, attrs: str = "") -> str:
    """Print settings as <metadata> lines (Orca/Bambu: plain key; PrusaSlicer: type="object"/"volume")."""
    return "".join(f'{indent}<metadata {attrs}key={quoteattr(k)} value={quoteattr(v)}/>\n' for k, v in settings.items())


def _prusa(settings: dict, part_level: bool, warnings: list[str]) -> dict[str, str]:
    out, warn = PS.to_prusa(settings, part_level=part_level)
    warnings += [w for w in warn if w not in warnings]
    return out


def _slot_warnings(items) -> list[str]:
    w, cols = [], {}
    for s, _, _ in items:
        cols.setdefault(int(s["filament"]), set()).add(s["color"].lower())
    if max(cols) > 4:
        w.append(f"Filament slots up to {max(cols)} are used; one ACE Pro has 4 (slots 5-8 = second ACE).")
    for k, v in cols.items():
        if len(v) > 1:
            w.append(f"Slot {k} has parts with different colours ({', '.join(sorted(v))}); they will print in the same filament.")
    return w


MULTI_PLATE_WARNING = ("Several beds in one 3MF: Orca, Bambu Studio and Anycubic Slicer Next open a file without "
                       "project settings as geometry on one plate, so beds 2+ end up beside the build plate. "
                       "Export one file per bed (split_plates) or only one bed (plate) instead.")

FIRST_LAYER_MM = 0.2  # first layer height of the slicer's default process (Orca / Anycubic / Prusa 0.4 nozzle)


def pause_layer_top(at_mm: float, layer_height: float, first_layer: float = FIRST_LAYER_MM) -> float:
    """Top of the first layer above at_mm - the layer the printer pauses before (same rule as slice_plate).
    Slicers attach a per-layer pause to the layer nearest its height, so the exact layer top is written."""
    if at_mm < first_layer - 1e-6:
        return round(first_layer, 4)
    k = math.floor((at_mm - first_layer) / layer_height + 1e-6) + 1
    return round(first_layer + k * layer_height, 4)


def _part_pauses(proj: Project, items, single_plate: bool) -> dict[int, list[float]]:
    """pause_at heights per plate number in the file (plate 1 when a single plate is exported)."""
    out: dict[int, set[float]] = {}
    for s, _, _ in items:
        hs = proj.build(s["name"])["info"].get("pause_at") or []
        if hs:
            out.setdefault(1 if single_plate else int(s["plate"]), set()).update(float(h) for h in hs)
    return {k: sorted(v) for k, v in sorted(out.items())}


def _pause_xml(flavor: str, pauses: dict[int, list[dict]], multi_slot: dict[int, bool]) -> tuple[str, str]:
    """Per-layer pause events as the slicer stores them in a project 3MF (type 1 = pause print)."""
    def code(tag: str, zkey: str, p: dict) -> str:
        msg = f"CAD-Studio: pause at {p['at_mm']:g} mm"
        return (f'<{tag} {zkey}="{p["layer_top_mm"]:g}" type="1" extruder="1" color="" '
                f'extra={quoteattr(msg)} gcode="M601"/>')
    if flavor == "prusa":
        rows = sorted({p["layer_top_mm"]: p for ps in pauses.values() for p in ps}.values(),
                      key=lambda p: p["layer_top_mm"])
        mode = "MultiExtruder" if any(multi_slot.values()) else "SingleExtruder"
        body = "\n".join(code("code", "print_z", p) for p in rows)
        return ("Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml",
                f'<?xml version="1.0" encoding="utf-8"?>\n<custom_gcodes_per_print_z>\n{body}\n'
                f'<mode value="{mode}"/>\n</custom_gcodes_per_print_z>\n')
    plates = []
    for k, ps in sorted(pauses.items()):
        mode = "MultiExtruder" if multi_slot.get(k) else "SingleExtruder"
        rows = "\n".join(code("layer", "top_z", p) for p in ps)
        plates.append(f'<plate>\n<plate_info id="{k}"/>\n{rows}\n<mode value="{mode}"/>\n</plate>')
    return ("Metadata/custom_gcode_per_layer.xml",
            '<?xml version="1.0" encoding="utf-8"?>\n<custom_gcodes_per_layer>\n' + "\n".join(plates)
            + "\n</custom_gcodes_per_layer>\n")


def export_3mf(proj: Project, path: str | Path | None = None, mode: str = "assembly", flavor: str = "orca",
               only: list[str] | None = None, object_name: str | None = None, thumbnail: bytes | None = None,
               filament_density_g_cm3: float = 1.24, filament_price_eur_kg: float | None = None,
               print_rate_cm3_per_hour: float | None = 15.0, plate: int | None = None,
               split_plates: bool = False, filament_map: dict[int, int] | None = None,
               print_settings: dict | None = None, pauses: bool = True) -> dict:
    """plate: export only that plate (centred on a single bed). split_plates: one file per plate.
    pauses: write the parts' `pause_at` heights as per-layer pauses (Orca/Bambu/Anycubic:
    Metadata/custom_gcode_per_layer.xml, PrusaSlicer: Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml);
    the slicer applies them when the file is opened as a project. They assume the exported layer height.
    filament_map: renumber filament slots in the file, e.g. {1: 1, 2: 1} prints everything with filament 1.
    print_settings: object-level print settings (friendly names, see printsettings.FIELDS); default: the
    project's own (profile + overrides). Per-part settings always come from the parts."""
    path = Path(path) if path else proj.dir / "exports" / f"{proj.name}.3mf"
    if path.suffix.lower() != ".3mf":
        path = path.with_suffix(".3mf")
    if split_plates and plate is None:
        used = sorted({int(s["plate"]) for s, _, _ in exportable_meshes(proj, only)})
        results = []
        for k in used:
            sub = path.with_name(f"{path.stem}-plate{k}.3mf") if len(used) > 1 else path
            results.append(export_3mf(proj, sub, mode=mode, flavor=flavor, only=only, object_name=object_name,
                                      thumbnail=thumbnail, filament_density_g_cm3=filament_density_g_cm3,
                                      filament_price_eur_kg=filament_price_eur_kg,
                                      print_rate_cm3_per_hour=print_rate_cm3_per_hour, plate=k,
                                      filament_map=filament_map, print_settings=print_settings,
                                      pauses=pauses))
        out = {"paths": [r["path"] for r in results], "flavor": flavor, "mode": mode,
               "plates": {str(k): r for k, r in zip(used, results)},
               "warnings": [w for r in results for w in r["warnings"]],
               "total_g_solid_estimate": round(sum(r["total_g_solid_estimate"] for r in results), 1)}
        if print_rate_cm3_per_hour:
            out["print_time_hours_estimate"] = round(sum(r["print_time_hours_estimate"] for r in results), 2)
        return out
    items = exportable_meshes(proj, only, plate=plate)
    if filament_map:
        items = [({**s, "filament": int(filament_map.get(int(s["filament"]), s["filament"]))}, V, F)
                 for s, V, F in items]
    count = 1 if plate is not None else proj.plate_count
    if plate is not None:
        items, warnings = _place(items, center=True, label=f"Plate {plate}")
        plates_used = [plate]
    else:
        items, warnings, plates_used = _place_plates(items, count)
    if flavor == "orca" and len(plates_used) > 1:
        warnings.append(MULTI_PLATE_WARNING)
    if flavor == "prusa" and len(plates_used) > 1:
        warnings.append("PrusaSlicer has no build plates: all plates are laid out side by side on one bed. "
                        "Use split_plates (one file per plate) instead.")
    path.parent.mkdir(parents=True, exist_ok=True)
    object_name = object_name or proj.name
    obj_ps = PS.normalize(print_settings) if print_settings is not None else PS.project_settings(proj.data)
    part_ps = {s["name"]: PS.part_settings(s) for s, _, _ in items}

    # material table: one entry per part colour
    colors = []
    for s, _, _ in items:
        c = _color(s["color"])
        if c not in colors:
            colors.append(c)
    bm = "\n".join(f'   <base name={quoteattr(c)} displaycolor="{c}"/>' for c in colors)

    now = _dt.date.today().isoformat()
    head = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
            f' <metadata name="Application">CAD-Studio</metadata>\n'
            f' <metadata name="Title">{escape(object_name)}</metadata>\n'
            f' <metadata name="CreationDate">{now}</metadata>\n'
            f' <resources>\n  <basematerials id="1">\n{bm}\n  </basematerials>\n')

    objects, build, cfg = [], [], []
    if flavor == "prusa":
        groups = [items] if mode == "assembly" else [[it] for it in items]
        oid = 2
        for grp in groups:
            Vs, Fs, vols, off_v, off_t = [], [], [], 0, 0
            for s, V, F in grp:
                Vs.append(V)
                Fs.append(F + off_v)
                vols.append((s, off_t, off_t + len(F) - 1))
                off_v += len(V)
                off_t += len(F)
            name = object_name if mode == "assembly" else grp[0][0]["name"]
            pindex = colors.index(_color(grp[0][0]["color"]))
            objects.append(f'  <object id="{oid}" type="model" name={quoteattr(name)} pid="1" pindex="{pindex}">\n'
                           f'{_mesh_xml(np.vstack(Vs), np.vstack(Fs))}\n  </object>')
            build.append(f'  <item objectid="{oid}" printable="1"/>')
            vx = "\n".join(
                f'  <volume firstid="{a}" lastid="{b}">\n'
                f'   <metadata type="volume" key="name" value={quoteattr(s["name"])}/>\n'
                f'   <metadata type="volume" key="extruder" value="{int(s["filament"])}"/>\n'
                + _settings_xml(_prusa(part_ps[s["name"]], True, warnings), "   ", 'type="volume" ')
                + '  </volume>' for s, a, b in vols)
            cfg.append(f' <object id="{oid}" instances_count="1">\n'
                       f'  <metadata type="object" key="name" value={quoteattr(name)}/>\n'
                       f'  <metadata type="object" key="extruder" value="{int(grp[0][0]["filament"])}"/>\n'
                       + _settings_xml(_prusa(obj_ps, False, warnings), "  ", 'type="object" ')
                       + f'{vx}\n </object>')
            oid += 1
        cfg_name = "Metadata/Slic3r_PE_model.config"
        cfg_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg) + "\n</config>\n"
    else:  # orca / bambu / anycubic slicer next
        oid = 2
        part_ids = []
        for s, V, F in items:
            pindex = colors.index(_color(s["color"]))
            objects.append(f'  <object id="{oid}" type="model" name={quoteattr(s["name"])} pid="1" pindex="{pindex}">\n'
                           f'{_mesh_xml(V, F)}\n  </object>')
            part_ids.append((oid, s))
            oid += 1
        if mode == "assembly":  # one multi-colour object per plate
            groups = [[p for p in part_ids if int(p[1]["plate"]) == k] for k in plates_used]
        else:
            groups = [[p] for p in part_ids]
        plate_members: dict[int, list[int]] = {}
        for grp in groups:
            name = object_name if mode == "assembly" else grp[0][1]["name"]
            if mode == "assembly" and len(plates_used) > 1:
                name = f"{object_name} - plate {int(grp[0][1]['plate'])}"
            plate_members.setdefault(int(grp[0][1]["plate"]) if plate is None else 1, []).append(oid)
            comps = "\n".join(f'    <component objectid="{pid}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>' for pid, _ in grp)
            objects.append(f'  <object id="{oid}" type="model" name={quoteattr(name)}>\n'
                           f'   <components>\n{comps}\n   </components>\n  </object>')
            build.append(f'  <item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/>')
            parts_cfg = "\n".join(
                f'  <part id="{pid}" subtype="normal_part">\n'
                f'   <metadata key="name" value={quoteattr(s["name"])}/>\n'
                f'   <metadata key="matrix" value="{IDENTITY}"/>\n'
                f'   <metadata key="extruder" value="{int(s["filament"])}"/>\n'
                + _settings_xml(PS.to_orca(part_ps[s["name"]], part_level=True), "   ")
                + '  </part>' for pid, s in grp)
            cfg.append(f' <object id="{oid}">\n'
                       f'  <metadata key="name" value={quoteattr(name)}/>\n'
                       f'  <metadata key="extruder" value="{int(grp[0][1]["filament"])}"/>\n'
                       + _settings_xml(PS.to_orca(obj_ps), "  ")
                       + f'{parts_cfg}\n </object>')
            oid += 1
        for k in range(1, count + 1):  # plate membership (Orca/Bambu); empty plates are kept as empty plates
            insts = "\n".join(
                f'  <model_instance>\n'
                f'   <metadata key="object_id" value="{o}"/>\n'
                f'   <metadata key="instance_id" value="0"/>\n'
                f'   <metadata key="identify_id" value="{o}"/>\n'
                f'  </model_instance>' for o in plate_members.get(k, []))
            cfg.append(f' <plate>\n  <metadata key="plater_id" value="{k}"/>\n'
                       f'  <metadata key="plater_name" value=""/>\n  <metadata key="locked" value="false"/>\n'
                       + (insts + "\n" if insts else "") + " </plate>")
        cfg_name = "Metadata/model_settings.config"
        cfg_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg) + "\n</config>\n"

    pause_file = None
    pause_info: dict[str, list[dict]] = {}
    if pauses:
        heights = _part_pauses(proj, items, single_plate=plate is not None)
        if heights:
            lh = float(obj_ps.get("layer_height_mm") or 0.2)
            per_plate = {k: [{"at_mm": h, "layer_top_mm": pause_layer_top(h, lh)} for h in hs]
                         for k, hs in heights.items()}
            slots: dict[int, set[int]] = {}
            for s, _, _ in items:
                slots.setdefault(1 if plate is not None else int(s["plate"]), set()).add(int(s["filament"]))
            pause_file = _pause_xml(flavor, per_plate, {k: len(v) > 1 for k, v in slots.items()})
            pause_info = {str(k): v for k, v in per_plate.items()}
            warnings.append(f"Print pauses are in the file for {lh:g} mm layers (first layer {FIRST_LAYER_MM:g} mm). "
                            "Open the 3MF as a project ('Open as project', not 'import geometry only') to keep "
                            "them; check the pause marks on the layer slider after slicing.")

    model = head + "\n".join(objects) + "\n </resources>\n <build>\n" + "\n".join(build) + "\n </build>\n</model>\n"

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        rels = RELS if thumbnail else "\n".join(ln for ln in RELS.splitlines() if "thumbnail" not in ln)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr(cfg_name, cfg_xml)
        if thumbnail:
            z.writestr("Metadata/thumbnail.png", thumbnail)
        if pause_file:
            z.writestr(*pause_file)

    fil = {}
    grams_per_slot: dict[int, float] = {}
    for s, V, F in items:
        slot = int(s["filament"])
        fil.setdefault(slot, []).append(f'{s["name"]} ({s["color"]})')
        grams_per_slot[slot] = grams_per_slot.get(slot, 0.0) + mesh_volume(V, F) / 1000 * filament_density_g_cm3
    warnings += _slot_warnings(items)
    total_g = sum(grams_per_slot.values())
    result = {"path": str(path), "flavor": flavor, "mode": mode, "parts": [s["name"] for s, _, _ in items],
              "plates": {str(k): [s["name"] for s, _, _ in items if plate is not None or int(s["plate"]) == k]
                         for k in plates_used},
              "filament_slots": {str(k): v for k, v in sorted(fil.items())}, "warnings": warnings,
              "triangles": int(sum(len(F) for _, _, F in items)),
              # a rough estimate: solid-model volume x density, so it ignores infill/perimeters/supports and
              # is an upper bound for anything printed below 100% infill (which is most prints)
              "filament_g_solid_estimate": {str(k): round(v, 1) for k, v in sorted(grams_per_slot.items())},
              "total_g_solid_estimate": round(total_g, 1)}
    if pause_info:
        result["pauses"] = pause_info
    if obj_ps or any(part_ps.values()):
        result["print_settings"] = {"object": obj_ps, "parts": {k: v for k, v in part_ps.items() if v}}
    if filament_price_eur_kg is not None:
        result["cost_eur_solid_estimate"] = round(total_g / 1000 * filament_price_eur_kg, 2)
    if print_rate_cm3_per_hour:
        # same upper-bound logic as the weight estimate: volume-based, so it assumes 100% infill and no
        # travel/retraction overhead - treat it as a ceiling, not a prediction (the slicer's own estimate,
        # after it has sliced with your real settings, will be more accurate and is usually lower)
        total_cm3 = total_g / filament_density_g_cm3
        result["print_time_hours_estimate"] = round(total_cm3 / print_rate_cm3_per_hour, 2)
    return result


def export_stl(proj: Project, path: str | Path | None = None, only: list[str] | None = None,
               separate: bool = True) -> dict:
    """Binary STL. separate=True -> one file per part (in a folder), else one merged file."""
    import trimesh

    items = exportable_meshes(proj, only)
    by_plate: dict[int, list] = {}
    for it in items:
        by_plate.setdefault(int(it[0]["plate"]), []).append(it)
    placed, warnings = {}, []
    for k, grp in by_plate.items():  # every plate on its own bed (z=0); they would overlap if merged
        pts, w = _place(grp, center=False, label=f"Plate {k}" if len(by_plate) > 1 else "Model")
        warnings += w
        placed.update({s["name"]: (s, V, F) for s, V, F in pts})
    items = [placed[s["name"]] for s, _, _ in items]
    base = Path(path) if path else proj.dir / "exports"
    files = []
    if separate:
        base = base if base.suffix == "" else base.parent
        base.mkdir(parents=True, exist_ok=True)
        for s, V, F in items:
            f = base / f"{proj.name}_{slugify(s['name'])}.stl"
            trimesh.Trimesh(V, F, process=False).export(f)
            files.append(str(f))
    else:
        f = base if base.suffix.lower() == ".stl" else base / f"{proj.name}.stl"
        f.parent.mkdir(parents=True, exist_ok=True)
        off, Vs, Fs = 0, [], []
        for _, V, F in items:
            Vs.append(V)
            Fs.append(F + off)
            off += len(V)
        trimesh.Trimesh(np.vstack(Vs), np.vstack(Fs), process=False).export(f)
        files.append(str(f))
    return {"files": files, "warnings": warnings}


def export_step(proj: Project, path: str | Path | None = None, only: list[str] | None = None) -> dict:
    """STEP of the CAD parts (mesh imports are skipped) – for use in Fusion 360/FreeCAD."""
    import build123d as bd

    shapes = []
    for p in proj.parts:
        if only and p["name"] not in only:
            continue
        e = proj.build(p["name"])
        if e["info"].get("ok") and e["shape"] is not None:
            sh = e["shape"]
            sh.label = p["name"]
            shapes.append(sh)
    if not shapes:
        raise PartError("No CAD parts to export as STEP")
    path = Path(path) if path else proj.dir / "exports" / f"{proj.name}.step"
    path.parent.mkdir(parents=True, exist_ok=True)
    bd.export_step(bd.Compound(children=shapes), str(path))
    return {"path": str(path), "parts": [s.label for s in shapes]}
