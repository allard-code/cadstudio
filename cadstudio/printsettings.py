# SPDX-License-Identifier: GPL-3.0-or-later
"""Print settings that travel with the design: a profile per project (what the part is *for*) plus overrides,
and per-part overrides (e.g. a strong body with a decorative inlay).

They are written into the 3MF as per-object / per-part settings, so the slicer opens the file with them already
applied (Orca / Bambu / Anycubic Slicer Next: Metadata/model_settings.config; PrusaSlicer:
Metadata/Slic3r_PE_model.config), and slice_plate uses them for the bundled OrcaSlicer.

Settings use friendly names (FIELDS); to_orca() / to_prusa() translate them to slicer keys.
"""
from __future__ import annotations

from typing import Any

# friendly name -> (type, orca key, prusa key, object_only)
# object_only: the slicer only accepts it per object (layer height, supports, brim), not per part/volume.
FIELDS: dict[str, tuple[type, str, str, bool]] = {
    "layer_height_mm": (float, "layer_height", "layer_height", True),
    "wall_loops": (int, "wall_loops", "perimeters", False),
    "top_layers": (int, "top_shell_layers", "top_solid_layers", False),
    "bottom_layers": (int, "bottom_shell_layers", "bottom_solid_layers", False),
    "infill_percent": (float, "sparse_infill_density", "fill_density", False),
    "infill_pattern": (str, "sparse_infill_pattern", "fill_pattern", False),
    "supports": (bool, "enable_support", "support_material", True),
    "support_type": (str, "support_type", "support_material_style", True),
    "brim_width_mm": (float, "brim_width", "brim_width", True),
}

INFILL_PATTERNS = {
    "rectilinear", "alignedrectilinear", "zig-zag", "crosshatch", "line", "grid", "triangles", "tri-hexagon",
    "cubic", "adaptivecubic", "quartercubic", "supportcubic", "lightning", "honeycomb", "3dhoneycomb",
    "lateral-honeycomb", "lateral-lattice", "hilbertcurve", "archimedeanchords", "octagramspiral", "gyroid",
    "concentric",
}
# PrusaSlicer knows fewer patterns; the rest are left out of a prusa-flavour file (with a warning)
PRUSA_PATTERNS = {"rectilinear", "alignedrectilinear", "grid", "triangles", "stars", "cubic", "line", "concentric",
                  "honeycomb", "3dhoneycomb", "gyroid", "hilbertcurve", "archimedeanchords", "octagramspiral",
                  "adaptivecubic", "supportcubic", "lightning"}
SUPPORT_TYPES = {"normal": ("normal(auto)", "grid"), "tree": ("tree(auto)", "organic")}

# What the part is for -> settings on top of the slicer's default process. "standard" = slicer defaults.
PROFILES: dict[str, dict[str, Any]] = {
    "standard": {},
    "functional": {"wall_loops": 4, "top_layers": 5, "bottom_layers": 4, "infill_percent": 30,
                   "infill_pattern": "gyroid"},
    "strong": {"wall_loops": 6, "top_layers": 6, "bottom_layers": 5, "infill_percent": 50,
               "infill_pattern": "gyroid"},
    "watertight": {"wall_loops": 5, "top_layers": 7, "bottom_layers": 6, "infill_percent": 25,
                   "infill_pattern": "gyroid"},
    "decorative": {"wall_loops": 2, "top_layers": 4, "bottom_layers": 3, "infill_percent": 10,
                   "infill_pattern": "grid"},
    "draft": {"layer_height_mm": 0.28, "wall_loops": 2, "top_layers": 3, "bottom_layers": 3, "infill_percent": 10,
              "infill_pattern": "grid"},
    "fine": {"layer_height_mm": 0.12, "wall_loops": 3, "top_layers": 7, "bottom_layers": 5},
}

PROFILE_HELP = {
    "standard": "slicer defaults (0.20mm Standard process)",
    "functional": "brackets, holders, clips, housings: 4 walls, 30% gyroid",
    "strong": "load-bearing parts, hinges, tool parts: 6 walls, 50% gyroid",
    "watertight": "ducts, containers, vases that must not leak: 5 walls, extra top/bottom layers",
    "decorative": "figures, signs, inlays that carry no load: 2 walls, 10% infill",
    "draft": "quick fit test: 0.28 mm layers, 2 walls, 10% infill",
    "fine": "small detailed parts, smooth curved tops: 0.12 mm layers",
}


class PrintSettingsError(ValueError):
    pass


def _coerce(key: str, value):
    typ = FIELDS[key][0]
    if typ is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if typ is str:
        v = str(value).strip().lower()
        if key == "infill_pattern":
            v = {"zigzag": "zig-zag", "aligned_rectilinear": "alignedrectilinear", "3d_honeycomb": "3dhoneycomb",
                 "trihexagon": "tri-hexagon", "lines": "line"}.get(v, v)
            if v not in INFILL_PATTERNS:
                raise PrintSettingsError(f"Unknown infill_pattern '{value}'. Use one of: "
                                         f"{', '.join(sorted(INFILL_PATTERNS))}")
        elif key == "support_type":
            v = v.split("(")[0]
            if v not in SUPPORT_TYPES:
                raise PrintSettingsError(f"support_type must be one of {sorted(SUPPORT_TYPES)}, not '{value}'")
        return v
    try:
        v = typ(value)
    except (TypeError, ValueError) as e:
        raise PrintSettingsError(f"{key} must be a number, not {value!r}") from e
    limits = {"layer_height_mm": (0.04, 0.4), "wall_loops": (1, 20), "top_layers": (0, 50), "bottom_layers": (0, 50),
              "infill_percent": (0, 100), "brim_width_mm": (0, 50)}
    lo, hi = limits[key]
    if not lo <= v <= hi:
        raise PrintSettingsError(f"{key} must be between {lo} and {hi}, not {v}")
    return v


def normalize(settings: dict | None, part_level: bool = False) -> dict:
    """Validate friendly settings (None values dropped). part_level: only per-part (region) settings allowed."""
    out = {}
    for k, v in (settings or {}).items():
        if v is None:
            continue
        if k not in FIELDS:
            raise PrintSettingsError(f"Unknown print setting '{k}'. Known: {', '.join(FIELDS)}")
        if part_level and FIELDS[k][3]:
            raise PrintSettingsError(f"'{k}' can only be set for the whole object (project / plate), "
                                     f"not for one part. Per-part settings: "
                                     f"{', '.join(n for n, f in FIELDS.items() if not f[3])}")
        out[k] = _coerce(k, v)
    return out


def profile_settings(profile: str | None, part_level: bool = False) -> dict:
    if not profile:
        return {}
    p = profile.strip().lower()
    if p not in PROFILES:
        raise PrintSettingsError(f"Unknown profile '{profile}'. Profiles: "
                                 + "; ".join(f"{k} ({v})" for k, v in PROFILE_HELP.items()))
    return {k: v for k, v in PROFILES[p].items() if not (part_level and FIELDS[k][3])}


def project_settings(data: dict) -> dict:
    """Effective project-level settings: profile, then overrides."""
    ps = data.get("print") or {}
    return {**profile_settings(ps.get("profile")), **(ps.get("overrides") or {})}


def part_settings(spec: dict) -> dict:
    ps = spec.get("print") or {}
    return {**profile_settings(ps.get("profile"), part_level=True), **(ps.get("overrides") or {})}


def _fmt(key: str, v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if key in ("infill_percent",):
        return f"{float(v):g}%"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def to_orca(settings: dict, part_level: bool = False) -> dict[str, str]:
    out = {}
    for k, v in settings.items():
        if part_level and FIELDS[k][3]:
            continue
        if k == "support_type":
            v = SUPPORT_TYPES[v][0]
        out[FIELDS[k][1]] = _fmt(k, v)
    return out


def to_prusa(settings: dict, part_level: bool = False) -> tuple[dict[str, str], list[str]]:
    out, warn = {}, []
    for k, v in settings.items():
        if part_level and FIELDS[k][3]:
            continue
        if k == "support_type":
            v = SUPPORT_TYPES[v][1]
        if k == "infill_pattern" and v not in PRUSA_PATTERNS:
            warn.append(f"PrusaSlicer has no '{v}' infill; the file uses the slicer's default pattern.")
            continue
        out[FIELDS[k][2]] = _fmt(k, v)
    return out, warn
