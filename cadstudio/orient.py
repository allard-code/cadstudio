# SPDX-License-Identifier: GPL-3.0-or-later
"""Print orientation: which side of a part (or a group of parts printed together) should face the bed.

Candidates are the six axis directions plus the large flat faces of the convex hull (any of those can rest flat
on the bed). Each is scored on
  * support area   - downward faces steeper than the overhang angle that are not on the bed (need support),
  * bed contact    - flat area on the bed (adhesion, no tipping),
  * height         - print time and wobble,
  * load alignment - optional: printed parts are weakest across the layer lines, so a load along Z is bad.
numpy only (the convex hull comes from trimesh, already a dependency).
"""
from __future__ import annotations

import math

import numpy as np

from .project import rot_matrix

DOWN = np.array([0.0, 0.0, -1.0])


def euler_from_matrix(R: np.ndarray) -> list[float]:
    """Inverse of project.rot_matrix (R = Rz @ Ry @ Rx) -> [rx, ry, rz] in degrees, snapped near whole degrees."""
    sy = -R[2, 0]
    if abs(sy) < 1 - 1e-9:
        ry = math.asin(max(-1.0, min(1.0, sy)))
        rx = math.atan2(R[2, 1], R[2, 2])
        rz = math.atan2(R[1, 0], R[0, 0])
    else:  # gimbal lock: ry = +-90, only rx - rz (or rx + rz) is defined -> put it all in rz
        ry = math.copysign(math.pi / 2, sy)
        rx = 0.0
        rz = math.atan2(-R[0, 1], R[1, 1])
    out = []
    for a in (rx, ry, rz):
        d = math.degrees(a)
        r = round(d)
        d = float(r) if abs(d - r) < 1e-6 else round(d, 4)
        out.append(0.0 if d == 0 else d)
    return out


def rotation_to_down(d: np.ndarray) -> np.ndarray:
    """Smallest rotation that turns direction d to point straight down (-Z)."""
    d = np.asarray(d, float)
    d = d / np.linalg.norm(d)
    c = float(np.dot(d, DOWN))
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:  # pointing up: flip over the X axis
        return rot_matrix(180, 0, 0)
    v = np.cross(d, DOWN)
    s = np.linalg.norm(v)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * ((1 - c) / s**2)


def _face_data(V: np.ndarray, F: np.ndarray):
    tri = V[F]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(n, axis=1)
    ok = area2 > 1e-12
    n[ok] /= area2[ok, None]
    return tri, n, area2 / 2


def _candidate_directions(V: np.ndarray, F: np.ndarray, max_faces: int = 12) -> list[tuple[np.ndarray, str]]:
    dirs: list[tuple[np.ndarray, str]] = [(DOWN.copy(), "current orientation")]
    for name, d in (("-X", [-1, 0, 0]), ("+X", [1, 0, 0]), ("-Y", [0, -1, 0]), ("+Y", [0, 1, 0]),
                    ("+Z", [0, 0, 1])):
        dirs.append((np.array(d, float), f"{name} side down"))
    try:
        import trimesh

        hull = trimesh.Trimesh(V, F, process=False).convex_hull
        order = np.argsort(-hull.facets_area)[:max_faces]
        for i in order:
            dirs.append((np.asarray(hull.facets_normal[i], float),
                         f"flat face {hull.facets_area[i]:.0f} mm2 down"))
    except Exception:  # degenerate geometry: axis directions are still fine
        pass
    uniq: list[tuple[np.ndarray, str]] = []
    for d, label in dirs:
        d = d / np.linalg.norm(d)
        if all(np.dot(d, u) < 0.9995 for u, _ in uniq):
            uniq.append((d, label))
    return uniq


def evaluate(V: np.ndarray, F: np.ndarray, R: np.ndarray, overhang_angle: float = 45.0,
             load: np.ndarray | None = None) -> dict:
    """Metrics of the mesh rotated by R (about any point - only the shape matters)."""
    Vr = V @ R.T
    tri, n, area = _face_data(Vr, F)
    zmin, zmax = Vr[:, 2].min(), Vr[:, 2].max()
    on_bed = (tri[:, :, 2].max(axis=1) - zmin) < 0.05
    down = n[:, 2] < -math.cos(math.radians(overhang_angle))
    support = float(area[down & ~on_bed].sum())
    contact = float(area[on_bed & (n[:, 2] < -0.99)].sum())
    total = float(area.sum()) or 1.0
    lo, hi = Vr.min(axis=0), Vr.max(axis=0)
    out = {"support_area_mm2": round(support, 1), "support_pct_of_surface": round(100 * support / total, 1),
           "bed_contact_mm2": round(contact, 1), "height_mm": round(float(zmax - zmin), 2),
           "footprint_mm": [round(float(hi[0] - lo[0]), 1), round(float(hi[1] - lo[1]), 1)]}
    if load is not None:
        ld = R @ (load / np.linalg.norm(load))
        # 0 = load runs along the layers (strong), 1 = load pulls the layers apart (weakest)
        out["load_across_layers"] = round(abs(float(ld[2])), 2)
    return out


def _score(m: dict, total_area: float, max_dim: float, has_load: bool) -> float:
    s = 4.0 * m["support_area_mm2"] / total_area          # support material: the main cost
    s += 0.6 * m["height_mm"] / max_dim                    # taller = slower, more wobble
    s -= 0.8 * min(1.0, m["bed_contact_mm2"] / max(1.0, 0.25 * max_dim**2))  # a good flat base
    if m["bed_contact_mm2"] < 20:                          # point/edge contact: adhesion + tipping risk
        s += 0.6
    if has_load:
        s += 1.5 * m["load_across_layers"]
    return round(s, 3)


def parse_load(load) -> np.ndarray | None:
    if load is None or load == "" or load == []:
        return None
    if isinstance(load, str):
        axes = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        key = load.strip().lower().lstrip("+-")
        if key not in axes:
            raise ValueError(f"load_direction must be 'x', 'y', 'z' or a vector [x, y, z], not {load!r}")
        return np.array(axes[key], float)
    v = np.asarray(load, float).reshape(-1)
    if v.shape != (3,) or not np.linalg.norm(v):
        raise ValueError("load_direction vector must be 3 non-zero numbers [x, y, z]")
    return v


def suggest(V: np.ndarray, F: np.ndarray, overhang_angle: float = 45.0, load=None, count: int = 3) -> dict:
    """Rank candidate orientations of one mesh (the union of the parts printed together).
    Returns {"current": metrics, "candidates": [{rank, label, rotation (3x3 list), rotation_deg, ...metrics, score}]}"""
    V = np.asarray(V, float)
    F = np.asarray(F, int)
    load_v = parse_load(load)
    _, _, area = _face_data(V, F)
    total_area = float(area.sum()) or 1.0
    max_dim = float((V.max(axis=0) - V.min(axis=0)).max()) or 1.0
    rows = []
    for d, label in _candidate_directions(V, F):
        R = rotation_to_down(d)
        m = evaluate(V, F, R, overhang_angle, load_v)
        rows.append({"label": label, "rotation_deg": euler_from_matrix(R), **m,
                     "score": _score(m, total_area, max_dim, load_v is not None), "_R": R})
    current = next(r for r in rows if r["label"] == "current orientation")
    rows.sort(key=lambda r: (r["score"], r["label"] != "current orientation"))
    seen, uniq = set(), []
    for r in rows:  # mirror images (left side vs right side down) score the same: keep one
        key = (r["support_area_mm2"], r["bed_contact_mm2"], r["height_mm"], r.get("load_across_layers"))
        if key in seen and r["label"] != "current orientation":
            continue
        seen.add(key)
        uniq.append(r)
    rows = uniq
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"current": {k: v for k, v in current.items() if k != "_R"}, "candidates": rows[:max(1, count)],
            "all": rows}
