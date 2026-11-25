# SPDX-License-Identifier: GPL-3.0-or-later
"""Fit check of an assembly: overlap and clearance between every pair of assembly items.

Printed parts that have to go together need a gap: a gap smaller than about 0.2-0.3 mm closes up when printed
and the parts jam. check_fit() measures, for every pair of items that come close, how much they overlap
(mm3) and otherwise the smallest gap between them, and flags what is too tight. Pairs that are meant to touch
or press together (a pin in its hole, a part resting on another) are listed in `allow`.
"""
from __future__ import annotations

import fnmatch
from typing import Any

from .project import Project


def _allowed(a: str, b: str, allow: list) -> bool:
    for pat in allow or []:
        if isinstance(pat, str):
            pat = pat.split(":")
        if len(pat) != 2:
            continue
        p, q = pat
        if (fnmatch.fnmatch(a, p) and fnmatch.fnmatch(b, q)) or (fnmatch.fnmatch(a, q) and fnmatch.fnmatch(b, p)):
            return True
    return False


def check_fit(proj: Project, items: list[str] | None = None, allow: list | None = None,
              min_clearance: float = 0.3, overlap_tolerance_mm3: float = 0.01) -> dict[str, Any]:
    """Check every pair of (visible) assembly items.

    allow: pairs that may touch or overlap, as ["a", "b"] or "a:b", with * wildcards ("wheel*:axle*").
    Returns {"ok", "min_clearance_mm", "issues": [...], "pairs": [...], "skipped": [...]} where each pair is
    {a, b, status, overlap_mm3, clearance_mm}; status is "overlap" (solids intersect), "tight" (gap below
    min_clearance), "touch" (gap ~0, no overlap), "ok", or "allowed" (listed in allow). Only pairs whose
    bounding boxes come within min_clearance of each other are measured; the rest are far apart."""
    names = []
    skipped = []
    for a in proj.assembly:
        spec = proj.find_assembly_item(a["name"])
        if items and spec["name"] not in items:
            continue
        if not items and not spec["visible"]:
            continue
        e = proj.build_assembly_item(spec["name"])
        if not e["info"].get("ok"):
            skipped.append({"item": spec["name"], "reason": e["info"].get("error")})
        elif e["shape"] is None:
            skipped.append({"item": spec["name"], "reason": "no CAD solid (mesh only)"})
        else:
            names.append((spec["name"], e["shape"]))
    pairs, issues = [], []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            (a, sa), (b, sb) = names[i], names[j]
            ba, bb = sa.bounding_box(), sb.bounding_box()
            gap = max(ba.min.X - bb.max.X, bb.min.X - ba.max.X, ba.min.Y - bb.max.Y, bb.min.Y - ba.max.Y,
                      ba.min.Z - bb.max.Z, bb.min.Z - ba.max.Z)
            if gap > min_clearance:
                continue
            try:
                inter = sa & sb
                vol = float(inter.volume) if inter is not None else 0.0
            except Exception:  # noqa: BLE001 - a failing boolean must not stop the whole check
                vol = 0.0
            clearance = 0.0
            if vol <= overlap_tolerance_mm3:
                vol = 0.0
                try:
                    clearance = float(sa.distance_to(sb))
                except Exception:  # noqa: BLE001
                    clearance = float("nan")
            if _allowed(a, b, allow):
                status = "allowed"
            elif vol > 0:
                status = "overlap"
            elif clearance < 0.01:
                status = "touch"
            elif clearance < min_clearance:
                status = "tight"
            else:
                status = "ok"
            row = {"a": a, "b": b, "status": status, "overlap_mm3": round(vol, 3),
                   "clearance_mm": None if vol > 0 else round(clearance, 3)}
            pairs.append(row)
            if status in ("overlap", "tight", "touch"):
                issues.append(row)
    order = {"overlap": 0, "touch": 1, "tight": 2}
    issues.sort(key=lambda r: (order[r["status"]], -(r["overlap_mm3"] or 0), r["clearance_mm"] or 0))
    return {"ok": not any(r["status"] in ("overlap", "tight") for r in issues), "min_clearance_mm": min_clearance,
            "issues": issues, "pairs": pairs, "skipped": skipped}
