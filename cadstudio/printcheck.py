# SPDX-License-Identifier: GPL-3.0-or-later
"""Print-preparation checks on part meshes.

find_floating(): slices the meshes of one build plate into layers (like a slicer does) and reports "floating
regions" - areas of a layer that touch nothing in the layer below, so they would be printed in mid-air
(Orca/Bambu/Anycubic Slicer Next warn about these as "floating regions" / "floating cantilever").
An overhang or bridge that is attached to something printed earlier is *not* floating: a region counts as
supported as soon as it touches (8-connected, in the same layer) any area that overlaps the layer below.
Everything is numpy-only (no scipy / OpenGL), rasterised on a grid of `pitch_mm`.
"""
from __future__ import annotations

from collections import deque

import numpy as np


def _slice_segments(tris: np.ndarray, z: float) -> np.ndarray:
    """Intersection of triangles (n, 3, 3) with the plane Z=z -> segments (m, 2, 2) in XY."""
    zs = tris[:, :, 2]
    sel = (zs.min(axis=1) < z) & (zs.max(axis=1) > z)
    t = tris[sel]
    if not len(t):
        return np.zeros((0, 2, 2))
    pts = []
    masks = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        za, zb = t[:, a, 2], t[:, b, 2]
        m = (za - z) * (zb - z) < 0
        denom = np.where(m, zb - za, 1.0)
        s = np.where(m, (z - za) / denom, 0.0)
        pts.append(t[:, a, :2] + (t[:, b, :2] - t[:, a, :2]) * s[:, None])
        masks.append(m)
    pts = np.stack(pts, axis=1)          # (k, 3, 2)
    masks = np.stack(masks, axis=1)      # (k, 3)
    ok = masks.sum(axis=1) == 2          # a plane between vertex heights cuts exactly two edges
    pts, masks = pts[ok], masks[ok]
    order = np.argsort(~masks, axis=1, kind="stable")[:, :2]   # indices of the two cut edges
    return np.take_along_axis(pts, order[:, :, None], axis=1)


def _rasterise(segs: np.ndarray, x0: float, y0: float, nx: int, ny: int, pitch: float) -> np.ndarray:
    """Even-odd fill of a closed cross-section given as segments -> bool grid (ny, nx); cell centres sampled."""
    grid = np.zeros((ny, nx), dtype=bool)
    if not len(segs):
        return grid
    p, q = segs[:, 0], segs[:, 1]
    ylo, yhi = np.minimum(p[:, 1], q[:, 1]), np.maximum(p[:, 1], q[:, 1])
    j0 = np.ceil((ylo - y0) / pitch - 0.5).astype(int)
    j1 = np.ceil((yhi - y0) / pitch - 0.5).astype(int)           # exclusive: rows with ylo <= yc < yhi
    j0, j1 = np.clip(j0, 0, ny), np.clip(j1, 0, ny)
    cnt = j1 - j0
    keep = cnt > 0
    if not keep.any():
        return grid
    p, q, j0, cnt = p[keep], q[keep], j0[keep], cnt[keep]
    seg_idx = np.repeat(np.arange(len(cnt)), cnt)
    rows = j0[seg_idx] + (np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt))
    yc = y0 + (rows + 0.5) * pitch
    pa, pb = p[seg_idx], q[seg_idx]
    xs = pa[:, 0] + (pb[:, 0] - pa[:, 0]) * (yc - pa[:, 1]) / (pb[:, 1] - pa[:, 1])
    order = np.lexsort((xs, rows))
    rows, xs = rows[order], xs[order]
    first = np.r_[0, np.flatnonzero(np.diff(rows)) + 1]
    run = np.diff(np.r_[first, len(rows)])
    rank = np.arange(len(rows)) - np.repeat(first, run)
    start = rank % 2 == 0
    has_pair = np.r_[rows[1:] == rows[:-1], False]                # drop a dangling crossing (non-watertight mesh)
    s_idx = np.flatnonzero(start & has_pair)
    e_idx = s_idx + 1
    c0 = np.clip(np.ceil((xs[s_idx] - x0) / pitch - 0.5).astype(int), 0, nx)
    c1 = np.clip(np.ceil((xs[e_idx] - x0) / pitch - 0.5).astype(int), 0, nx)
    diff = np.zeros((ny, nx + 1), dtype=np.int32)
    np.add.at(diff, (rows[s_idx], c0), 1)
    np.add.at(diff, (rows[s_idx], c1), -1)
    return np.cumsum(diff[:, :nx], axis=1) > 0


def _dilate(a: np.ndarray) -> np.ndarray:
    """One step of 8-connected dilation."""
    out = a.copy()
    out[1:] |= a[:-1]
    out[:-1] |= a[1:]
    out[:, 1:] |= out[:, :-1].copy()
    out[:, :-1] |= out[:, 1:].copy()
    return out


def _components(mask: np.ndarray, max_pixels: int = 400_000) -> list[np.ndarray]:
    """8-connected components of a (small) bool mask -> list of (k, 2) [row, col] arrays."""
    pix = np.argwhere(mask)
    if len(pix) > max_pixels:          # pathological: report it as one blob instead of a slow flood fill
        return [pix]
    todo = {(int(r), int(c)) for r, c in pix}
    comps = []
    while todo:
        seed = todo.pop()
        comp, dq = [seed], deque([seed])
        while dq:
            r, c = dq.popleft()
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nb = (r + dr, c + dc)
                    if nb in todo:
                        todo.remove(nb)
                        comp.append(nb)
                        dq.append(nb)
        comps.append(np.array(comp))
    return comps


def find_floating(items: list[tuple[str, np.ndarray, np.ndarray]], layer_height: float = 0.2, pitch: float = 0.2,
                  min_area_mm2: float = 0.1, max_reports: int = 50) -> list[dict]:
    """Floating regions of the parts on one build plate.

    items: (name, V, F) per part, in plate coordinates (bed at Z=0). Parts support each other (a colour inlay
    resting on its base part is fine). Returns a list of islands sorted by height:
    {part, z_mm, area_mm2, center: [x, y], bbox: [xmin, ymin, xmax, ymax]}.
    A part that starts above the bed is reported at its lowest layer."""
    items = [(n, np.asarray(V, float), np.asarray(F, int)) for n, V, F in items if len(F)]
    if not items:
        return []
    allv = np.vstack([V for _, V, _ in items])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    x0, y0 = lo[0] - pitch, lo[1] - pitch
    nx = int(np.ceil((hi[0] - x0) / pitch)) + 2
    ny = int(np.ceil((hi[1] - y0) / pitch)) + 2
    tris = [(n, V[F]) for n, V, F in items]
    zmax = hi[2]
    eps = 1e-6
    prev_all = None
    found: list[dict] = []
    k = 0
    while True:
        z = (k + 0.5) * layer_height + eps          # sample mid-layer, nudged off exact vertex heights
        if z > zmax:
            break
        layers = [(n, _rasterise(_slice_segments(t, z), x0, y0, nx, ny, pitch)) for n, t in tris]
        cur_all = np.zeros((ny, nx), dtype=bool)
        for _, g in layers:
            cur_all |= g
        if cur_all.any():
            if k == 0:
                supported = cur_all                          # first layer rests on the bed
            elif prev_all is None:
                supported = np.zeros_like(cur_all)
            else:
                # morphological reconstruction: start from what overlaps the layer below, grow within this layer
                supported = cur_all & prev_all
                while True:
                    grown = _dilate(supported) & cur_all
                    if (grown == supported).all():
                        break
                    supported = grown
            loose = cur_all & ~supported
            if loose.any():
                for comp in _components(loose):
                    area = len(comp) * pitch * pitch
                    if area < min_area_mm2:
                        continue
                    r, c = comp[:, 0], comp[:, 1]
                    owner = next((n for n, g in layers if g[r, c].any()), layers[0][0])
                    xs, ys = x0 + (c + 0.5) * pitch, y0 + (r + 0.5) * pitch
                    found.append({"part": owner, "z_mm": round(k * layer_height, 2), "area_mm2": round(area, 2),
                                  "center": [round(float(xs.mean()), 1), round(float(ys.mean()), 1)],
                                  "bbox": [round(float(xs.min()), 1), round(float(ys.min()), 1),
                                           round(float(xs.max()), 1), round(float(ys.max()), 1)]})
                    if len(found) >= max_reports:
                        return found
        prev_all = cur_all if cur_all.any() else None
        k += 1
    return found
