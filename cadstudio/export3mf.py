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
"""
from __future__ import annotations

import datetime as _dt
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from .project import BED, PartError, Project, exportable_meshes, slugify

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="text/xml"/>
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


def _place(items, center: bool):
    """Translate all meshes together so the group sits on the bed (z=0) and is centred on the plate."""
    allv = np.vstack([V for _, V, _ in items])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    size = hi - lo
    if center:
        shift = np.array([BED[0] / 2 - (lo[0] + hi[0]) / 2, BED[1] / 2 - (lo[1] + hi[1]) / 2, -lo[2]])
    else:
        shift = np.array([0.0, 0.0, -lo[2]])
    warn = []
    if size[0] > BED[0] or size[1] > BED[1] or size[2] > BED[2]:
        warn.append(f"Let op: model ({size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm) is groter dan het bed {BED}")
    return [(s, V + shift, F) for s, V, F in items], warn


def _slot_warnings(items) -> list[str]:
    w, cols = [], {}
    for s, _, _ in items:
        cols.setdefault(int(s["filament"]), set()).add(s["color"].lower())
    if max(cols) > 4:
        w.append(f"Er worden filament-slots tot {max(cols)} gebruikt; één ACE Pro heeft er 4 (slot 5-8 = tweede ACE).")
    for k, v in cols.items():
        if len(v) > 1:
            w.append(f"Slot {k} heeft parts met verschillende kleuren ({', '.join(sorted(v))}); ze printen in hetzelfde filament.")
    return w


def export_3mf(proj: Project, path: str | Path | None = None, mode: str = "assembly", flavor: str = "orca",
               only: list[str] | None = None, object_name: str | None = None, thumbnail: bytes | None = None) -> dict:
    items = exportable_meshes(proj, only)
    items, warnings = _place(items, center=True)
    path = Path(path) if path else proj.dir / "exports" / f"{proj.name}.3mf"
    if path.suffix.lower() != ".3mf":
        path = path.with_suffix(".3mf")
    path.parent.mkdir(parents=True, exist_ok=True)
    object_name = object_name or proj.name

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
                f'  </volume>' for s, a, b in vols)
            cfg.append(f' <object id="{oid}" instances_count="1">\n'
                       f'  <metadata type="object" key="name" value={quoteattr(name)}/>\n'
                       f'  <metadata type="object" key="extruder" value="{int(grp[0][0]["filament"])}"/>\n{vx}\n </object>')
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
        groups = [part_ids] if mode == "assembly" else [[p] for p in part_ids]
        for grp in groups:
            name = object_name if mode == "assembly" else grp[0][1]["name"]
            comps = "\n".join(f'    <component objectid="{pid}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>' for pid, _ in grp)
            objects.append(f'  <object id="{oid}" type="model" name={quoteattr(name)}>\n'
                           f'   <components>\n{comps}\n   </components>\n  </object>')
            build.append(f'  <item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/>')
            parts_cfg = "\n".join(
                f'  <part id="{pid}" subtype="normal_part">\n'
                f'   <metadata key="name" value={quoteattr(s["name"])}/>\n'
                f'   <metadata key="matrix" value="{IDENTITY}"/>\n'
                f'   <metadata key="extruder" value="{int(s["filament"])}"/>\n'
                f'  </part>' for pid, s in grp)
            cfg.append(f' <object id="{oid}">\n'
                       f'  <metadata key="name" value={quoteattr(name)}/>\n'
                       f'  <metadata key="extruder" value="{int(grp[0][1]["filament"])}"/>\n{parts_cfg}\n </object>')
            oid += 1
        cfg_name = "Metadata/model_settings.config"
        cfg_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg) + "\n</config>\n"

    model = head + "\n".join(objects) + "\n </resources>\n <build>\n" + "\n".join(build) + "\n </build>\n</model>\n"

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS if thumbnail else RELS.replace(
            '\n <Relationship Target="/Metadata/thumbnail.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>', ""))
        z.writestr("3D/3dmodel.model", model)
        z.writestr(cfg_name, cfg_xml)
        if thumbnail:
            z.writestr("Metadata/thumbnail.png", thumbnail)

    fil = {}
    for s, _, _ in items:
        fil.setdefault(int(s["filament"]), []).append(f'{s["name"]} ({s["color"]})')
    warnings += _slot_warnings(items)
    return {"path": str(path), "flavor": flavor, "mode": mode, "parts": [s["name"] for s, _, _ in items],
            "filament_slots": {str(k): v for k, v in sorted(fil.items())}, "warnings": warnings,
            "triangles": int(sum(len(F) for _, _, F in items))}


def export_stl(proj: Project, path: str | Path | None = None, only: list[str] | None = None,
               separate: bool = True) -> dict:
    """Binary STL. separate=True -> one file per part (in a folder), else one merged file."""
    import trimesh

    items = exportable_meshes(proj, only)
    items, warnings = _place(items, center=False)
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
        raise PartError("Geen CAD-parts om als STEP te exporteren")
    path = Path(path) if path else proj.dir / "exports" / f"{proj.name}.step"
    path.parent.mkdir(parents=True, exist_ok=True)
    bd.export_step(bd.Compound(children=shapes), str(path))
    return {"path": str(path), "parts": [s.label for s in shapes]}
