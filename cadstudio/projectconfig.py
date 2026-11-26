# SPDX-License-Identifier: GPL-3.0-or-later
"""Metadata/project_settings.config for multi-plate 3MF files.

OrcaSlicer, Bambu Studio and Anycubic Slicer Next only treat a 3MF as a *project* when it carries a project config.
Without one they import it as loose geometry: the <plate> blocks in model_settings.config are ignored (Orca) or
the objects are moved together to the centre of bed 1 (all of them), so beds 2+ end up beside the build plate.

The project config is a complete printer + process + filament config, in the same JSON layout the slicer writes
itself (checked against a project saved by OrcaSlicer 2.5.2): every printer and process key once, every filament
key as a list with one value per filament slot, plus the preset names. It is built from OrcaSlicer's system
profiles for the configured printer (CADSTUDIO_PRINTER), so it needs the profiles that ship in the Docker image;
without them build() returns None and the caller falls back to one file per plate.
"""
from __future__ import annotations

from . import slicer

# preset bookkeeping keys that are not print settings (the slicer drops them from a project config too)
_META = {"name", "from", "inherits", "instantiation", "type", "setting_id", "filament_id", "version", "description",
         "renamed_from", "is_custom_defined", "compatible_printers", "compatible_prints",
         "compatible_printers_condition", "compatible_prints_condition"}
# Orca's own version in its project configs; only used for "newer file" notices, which an untagged file never gets
_VERSION = "02.00.00.00"


def profiles_available() -> bool:
    try:
        return (slicer.profiles_dir() / slicer.DEFAULT_VENDOR / "machine").is_dir()
    except OSError:
        return False


def build(colours: list[str], materials: list[str] | None = None, printer: str | None = None,
          process: str | None = None, process_settings: dict[str, str] | None = None,
          vendor: str | None = None) -> dict | None:
    """Project config for len(colours) filament slots. colours: '#RRGGBB' per slot (slot 1 first);
    materials: material or preset name per slot (default PLA); process_settings: Orca keys/values applied on top
    of the process (printsettings.to_orca). None when the slicer profiles are not available."""
    if not colours or not profiles_available():
        return None
    vendor = vendor or slicer.DEFAULT_VENDOR
    printer = printer or slicer.DEFAULT_PRINTER
    try:
        machine = slicer.flatten("machine", printer, vendor)
        process = process or slicer.default_process(printer, vendor)
        proc = slicer.flatten("process", process, vendor)
        mats = list(materials or [])
        mats += [mats[-1] if mats else "PLA"] * (len(colours) - len(mats))
        fil_names = [slicer.filament_preset(m, printer, vendor) for m in mats[:len(colours)]]
        fils = [slicer.flatten("filament", n, vendor) for n in fil_names]
    except slicer.SlicerError:
        return None

    cfg: dict = {}
    for src in (machine, proc):
        cfg.update({k: v for k, v in src.items() if k not in _META})
    for k, v in (process_settings or {}).items():
        cfg[k] = v
    # filament keys: one value per slot (a preset holds a one-element list)
    for k in {k for f in fils for k in f if k not in _META}:
        vals = []
        for f in fils:
            v = f.get(k)
            if v is None:
                v = next((g[k] for g in fils if k in g), "")
            vals += v if isinstance(v, list) else [v]
        cfg[k] = vals
    n = len(fils)
    cfg["filament_colour"] = [c.upper() for c in colours]
    cfg.update({
        "name": "project_settings", "from": "project", "version": _VERSION,
        "printer_settings_id": printer, "print_settings_id": process, "filament_settings_id": fil_names,
        "inherits_group": [""] * (n + 2), "different_settings_to_system": [""] * (n + 2),
    })
    return cfg
