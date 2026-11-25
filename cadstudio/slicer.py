# SPDX-License-Identifier: GPL-3.0-or-later
"""Slicing with the OrcaSlicer command line (bundled in the Docker image under /opt/orca).

Printer / process / filament settings come from OrcaSlicer's own system profiles (resources/profiles/<vendor>).
They are "flattened" here (the `inherits` chain merged into one JSON per preset) so the CLI gets complete
settings regardless of how a given OrcaSlicer release resolves inheritance. Overrides (layer height, infill,
walls, ...) are applied on top of the process preset.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ORCA_HOME = Path(os.environ.get("CADSTUDIO_ORCA_HOME", "/opt/orca"))

DEFAULT_VENDOR = os.environ.get("CADSTUDIO_PRINTER_VENDOR", "Anycubic")
DEFAULT_PRINTER = os.environ.get("CADSTUDIO_PRINTER", "Anycubic Kobra S1 0.4 nozzle")

# friendly names for process overrides -> OrcaSlicer keys
OVERRIDE_KEYS = {
    "layer_height_mm": "layer_height",
    "infill_percent": "sparse_infill_density",
    "wall_loops": "wall_loops",
    "top_layers": "top_shell_layers",
    "bottom_layers": "bottom_shell_layers",
    "supports": "enable_support",
    "brim_width_mm": "brim_width",
}


class SlicerError(RuntimeError):
    pass


def orca_binary() -> Path | None:
    env = os.environ.get("CADSTUDIO_ORCA")
    # AppRun sets up the bundled environment (libexec/orca-slicer-env) before starting bin/orca-slicer
    for p in ([Path(env)] if env else []) + [ORCA_HOME / "AppRun", ORCA_HOME / "bin" / "orca-slicer"]:
        if p.exists():
            return p
    found = shutil.which("orca-slicer")
    return Path(found) if found else None


def profiles_dir() -> Path:
    env = os.environ.get("CADSTUDIO_ORCA_PROFILES")
    if env:
        return Path(env)
    for cand in (ORCA_HOME / "resources" / "profiles", ORCA_HOME / "share" / "OrcaSlicer" / "profiles",
                 ORCA_HOME / "usr" / "share" / "OrcaSlicer" / "profiles"):
        if cand.is_dir():
            return cand
    if ORCA_HOME.is_dir():
        for vendor in ORCA_HOME.rglob(DEFAULT_VENDOR):
            if (vendor / "machine").is_dir():
                return vendor.parent
    return ORCA_HOME / "resources" / "profiles"


def available() -> bool:
    return orca_binary() is not None and profiles_dir().is_dir()


def _index(vendor_dir: Path, kind: str) -> dict[str, Path]:
    idx = {}
    for f in (vendor_dir / kind).glob("*.json"):
        try:
            name = json.loads(f.read_text(encoding="utf-8")).get("name")
        except (OSError, ValueError):
            continue
        if name:
            idx[name] = f
    return idx


def flatten(kind: str, name: str, vendor: str = DEFAULT_VENDOR, root: Path | None = None) -> dict:
    """Merge a system preset with everything it inherits from -> one complete settings dict."""
    root = root or profiles_dir()
    idx = _index(root / vendor, kind)
    # filament presets may inherit from Orca's generic filament library
    if kind == "filament" and (root / "OrcaFilamentLibrary").is_dir():
        for k, v in _index(root / "OrcaFilamentLibrary", kind).items():
            idx.setdefault(k, v)
    if name not in idx:
        raise SlicerError(f"{kind} preset '{name}' not found for vendor {vendor}. "
                          f"Available: {', '.join(sorted(n for n in idx if not n.startswith('fdm_'))[:40])}")
    chain, cur = [], name
    while cur:
        if cur not in idx or cur in (c[0] for c in chain):
            break
        d = json.loads(idx[cur].read_text(encoding="utf-8"))
        chain.append((cur, d))
        cur = d.get("inherits", "")
    merged: dict = {}
    for _, d in reversed(chain):
        merged.update(d)
    merged["inherits"] = ""
    merged["name"] = name
    merged["from"] = "system"
    return merged


def list_presets(kind: str, vendor: str = DEFAULT_VENDOR, printer: str = DEFAULT_PRINTER) -> list[str]:
    """Instantiable presets of a kind that are compatible with the printer."""
    out = []
    for n, f in _index(profiles_dir() / vendor, kind).items():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(d.get("instantiation", "true")).lower() != "true":
            continue
        comp = d.get("compatible_printers") or []
        if kind == "machine" or printer in comp or (not comp and printer in n):
            out.append(n)
    return sorted(out)


def default_process(printer: str = DEFAULT_PRINTER, vendor: str = DEFAULT_VENDOR) -> str:
    return flatten("machine", printer, vendor).get("default_print_profile") or f"0.20mm Standard @{printer}"


def filament_preset(material: str, printer: str = DEFAULT_PRINTER, vendor: str = DEFAULT_VENDOR) -> str:
    """'PLA' -> 'Anycubic PLA @Anycubic Kobra S1 0.4 nozzle' (full preset names are passed through)."""
    if "@" in material or material.startswith(vendor):
        return material
    candidates = list_presets("filament", vendor, printer)
    want = f"{vendor} {material.strip()} @".lower()
    for c in candidates:
        if c.lower().startswith(want):
            return c
    raise SlicerError(f"No {vendor} filament preset for '{material}' on {printer}. "
                      f"Available: {', '.join(candidates)}")


def _fmt_value(key: str, value):
    if key == "sparse_infill_density":
        return f"{float(value):g}%"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _parse_gcode_stats(gcode: Path) -> dict:
    """Read the statistics block OrcaSlicer writes into the G-code."""
    stats: dict = {}
    try:
        with open(gcode, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            head = gcode.read_bytes()[:200_000].decode("utf-8", "replace")
            fh.seek(max(0, size - 400_000))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return stats
    text = head + "\n" + tail
    pats = {
        "print_time": (r";\s*(?:estimated printing time \(normal mode\)|model printing time|total estimated time)"
                       r"\s*[:=]\s*([^\n;]+)"),
        "filament_g": r";\s*(?:total filament used \[g\]|filament used \[g\])\s*[:=]\s*([\d.,\s]+)",
        "filament_mm": r";\s*filament used \[mm\]\s*[:=]\s*([\d.,\s]+)",
        "layers": r";\s*total layer number\s*[:=]\s*(\d+)",
    }
    for k, p in pats.items():
        m = re.search(p, text)
        if m:
            stats[k] = m.group(1).strip()
    if "filament_g" in stats:
        try:
            stats["filament_g"] = round(sum(float(x) for x in re.split(r"[,\s]+", stats["filament_g"]) if x), 1)
        except ValueError:
            pass
    return stats


def slice_3mf(model_3mf: Path, out_dir: Path, printer: str = DEFAULT_PRINTER, process: str | None = None,
              filaments: list[str] | None = None, overrides: dict | None = None, vendor: str = DEFAULT_VENDOR,
              timeout: int = 900, settings: dict[str, str] | None = None) -> dict:
    """Slice a single-plate 3MF. filaments: material or preset name per filament slot (1..n) used in the model.
    settings: process settings already in OrcaSlicer keys/format (printsettings.to_orca), applied before
    `overrides`. Returns {gcode, stats, log}."""
    exe = orca_binary()
    if exe is None:
        raise SlicerError("OrcaSlicer is not installed in this container (expected under /opt/orca). "
                          "Use the Docker image, or set CADSTUDIO_ORCA to the orca-slicer binary.")
    out_dir.mkdir(parents=True, exist_ok=True)
    filaments = filaments or ["PLA"]
    process = process or default_process(printer, vendor)
    with tempfile.TemporaryDirectory(prefix="cs-slice-") as tmp:
        tmp = Path(tmp)
        machine = flatten("machine", printer, vendor)
        proc = flatten("process", process, vendor)
        proc.update(settings or {})
        for k, v in (overrides or {}).items():
            if v is None:
                continue
            proc[OVERRIDE_KEYS.get(k, k)] = _fmt_value(OVERRIDE_KEYS.get(k, k), v)
        proc["compatible_printers"] = []
        fil_files = []
        for i, mat in enumerate(filaments):
            f = flatten("filament", filament_preset(mat, printer, vendor), vendor)
            f["compatible_printers"] = []
            p = tmp / f"filament{i + 1}.json"
            p.write_text(json.dumps(f), encoding="utf-8")
            fil_files.append(str(p))
        (tmp / "machine.json").write_text(json.dumps(machine), encoding="utf-8")
        (tmp / "process.json").write_text(json.dumps(proc), encoding="utf-8")
        work = tmp / "out"
        work.mkdir()
        cmd = [str(exe), "--slice", "1", "--allow-newer-file",
               "--load-settings", f"{tmp / 'machine.json'};{tmp / 'process.json'}",
               "--load-filaments", ";".join(fil_files),
               "--outputdir", str(work), str(model_3mf)]
        env = {**os.environ, "HOME": str(tmp), "XDG_RUNTIME_DIR": str(tmp), "LC_ALL": "C.UTF-8"}
        env.pop("DISPLAY", None)
        try:
            proc_run = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise SlicerError(f"OrcaSlicer timed out after {timeout} s") from e
        log = (proc_run.stdout or "")[-4000:] + (proc_run.stderr or "")[-4000:]
        result_json = {}
        if (work / "result.json").exists():
            try:
                result_json = json.loads((work / "result.json").read_text(encoding="utf-8"))
            except ValueError:
                pass
        gcodes = sorted(work.glob("*.gcode"))
        if proc_run.returncode != 0 or not gcodes:
            msg = result_json.get("error_string") or result_json.get("message") or ""
            raise SlicerError(f"OrcaSlicer failed (exit {proc_run.returncode}) {msg}\n{log[-3000:]}".strip())
        dest = out_dir / f"{model_3mf.stem}.gcode"
        shutil.move(str(gcodes[0]), dest)
        if vendor.lower() == "anycubic":
            add_anycubic_print_info(dest)
        stats = _parse_gcode_stats(dest)
        return {"gcode": str(dest), "stats": stats, "printer": printer, "process": process,
                "filaments": [filament_preset(m, printer, vendor) for m in filaments], "log": log[-1500:]}


def _footer_values(text: str, key: str) -> list[str] | None:
    m = re.search(r"^;\s*" + re.escape(key) + r"\s*=\s*(.+)$", text, re.M)
    if not m:
        return None
    return [v.strip() for v in re.split(r"[,;]", m.group(1)) if v.strip()]


def add_anycubic_print_info(gcode: Path) -> bool:
    """Append the per-filament metadata Anycubic Slicer Next writes, so the Anycubic cloud / ACE tooling
    (e.g. the Home Assistant anycubic_cloud integration) can map filaments to ACE slots.

    That tooling reads every '; key = value' comment after the first '; filament used' line and needs
    `paint_info` (a JSON list with paint_index + material_type per filament) and the 'filament used'
    values as lists - OrcaSlicer writes a single filament as a bare number. The lines are appended as
    comments at the very end, so the printer's own G-code is untouched. Returns False if the G-code has no
    'filament used [g]' statistics (nothing to describe)."""
    with open(gcode, "rb") as fh:
        fh.seek(0, 2)
        fh.seek(max(0, fh.tell() - 400_000))
        tail = fh.read().decode("utf-8", "replace")
    if re.search(r"^;\s*paint_info\s*=", tail, re.M):
        return True
    grams = _footer_values(tail, "filament used [g]")
    if not grams:
        return False
    types = _footer_values(tail, "filament_type") or []
    lines = ["", "; CAD-Studio: filament metadata for Anycubic cloud / ACE (Slicer Next format)"]
    for key in ("filament used [mm]", "filament used [cm3]", "filament used [g]"):
        vals = _footer_values(tail, key)
        if vals:
            nums = []
            for v in vals:
                try:
                    nums.append(float(v))
                except ValueError:
                    nums.append(0.0)
            lines.append(f"; {key} = {json.dumps(nums)}")
    paint = [{"paint_index": i, "material_type": (types[i] if i < len(types) else (types[0] if types else "PLA"))}
             for i, g in enumerate(grams) if _as_float(g) > 0]
    if not paint:
        paint = [{"paint_index": 0, "material_type": types[0] if types else "PLA"}]
    lines.append(f"; paint_info = {json.dumps(paint)}")
    with open(gcode, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return True


def _as_float(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0


_CUBE_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources>
  <object id="1" type="model" name="cube"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>
 </resources>
 <build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 125 125 0"/></build>
</model>
"""
_CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                  '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
         '</Relationships>')


def write_cube_3mf(path: Path, size: float = 20.0) -> Path:
    """A minimal one-object 3MF (a cube standing on the bed) for smoke tests."""
    import zipfile
    h = size / 2
    vs = [(x, y, z) for z in (0, size) for y in (-h, h) for x in (-h, h)]
    tris = [(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6), (0, 1, 4), (1, 5, 4),
            (2, 6, 3), (3, 6, 7), (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5)]
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in vs)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", _CUBE_MODEL.format(v=v, t=t))
    return path


def selftest(out_dir: str = "/tmp/cs-selftest") -> dict:
    """Slice a 20 mm cube with the default printer (used by the Docker CI smoke test)."""
    model = write_cube_3mf(Path(out_dir) / "cube.3mf")
    return slice_3mf(model, Path(out_dir))


if __name__ == "__main__":
    print(json.dumps(selftest(), indent=1))
