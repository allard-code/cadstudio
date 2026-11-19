# SPDX-License-Identifier: GPL-3.0-or-later
"""Off-screen preview renderer so Claude can *see* what it modelled.

Pure numpy z-buffer renderer (orthographic): triangles are densely point-sampled, depth-tested per pixel,
Lambert-shaded and outlined at silhouette/crease edges. No OpenGL needed, works headless on any OS.
"""
from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .project import PART_DEFAULTS, Project

VIEWS = {  # (elevation, azimuth) in degrees; azimuth 0 = looking from +X, -90 = from -Y (front)
    "iso": (30, -55),
    "front": (0, -90),
    "back": (0, 90),
    "left": (0, 180),
    "right": (0, 0),
    "top": (90, -90),
    "bottom": (-90, -90),
    "iso_back": (30, 125),
}
BG = np.array([246, 247, 249], dtype=np.float32)
MAX_SAMPLES = 9_000_000


def _hex(c: str) -> np.ndarray:
    c = (c or "#cccccc").lstrip("#")[:6]
    try:
        return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)
    except ValueError:
        return np.array([200, 200, 200], dtype=np.float32)


def _collect(proj: Project, parts: list[str] | None):
    items, errors = [], []
    for p in proj.parts:
        s = {**PART_DEFAULTS, **p}
        if parts and s["name"] not in parts:
            continue
        if not parts and not s["visible"]:
            continue
        e = proj.build(s["name"])
        if not e["info"].get("ok"):
            errors.append(f"{s['name']}: {e['info'].get('error')}")
            continue
        items.append((s, *e["mesh"]))
    return items, errors


def _basis(elev: float, azim: float):
    e, a = math.radians(elev), math.radians(azim)
    cam = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])  # towards viewer
    if abs(cam[2]) > 0.999:  # top / bottom: screen-up = +Y (top) so X right, Y up
        right = np.array([1.0, 0, 0])
        up = np.cross(cam, right)
        up = up if up[1] > 0 else -up
        if cam[2] < 0:
            up = -up
    else:
        right = np.cross(np.array([0, 0, 1.0]), cam)
        right /= np.linalg.norm(right)
        up = np.cross(cam, right)
    return right, up, cam


def _render_view(tris: np.ndarray, colors: np.ndarray, normals: np.ndarray, elev: float, azim: float,
                 W: int, H: int, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    right, up, cam = _basis(elev, azim)
    # fit scene bbox (all 8 corners) into the image
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    cx, cy = corners @ right, corners @ up
    span = max(np.ptp(cx), np.ptp(cy), 1e-6)
    scale = 0.9 * min(W, H) / span
    ox, oy = (cx.max() + cx.min()) / 2, (cy.max() + cy.min()) / 2

    def proj(P):
        return ((P @ right - ox) * scale + W / 2, H / 2 - (P @ up - oy) * scale, P @ cam)

    A, B, C = tris[:, 0], tris[:, 1], tris[:, 2]
    ax, ay, az = proj(A)
    bx, by, bz = proj(B)
    cx2, cy2, cz = proj(C)
    area = np.abs((bx - ax) * (cy2 - ay) - (cx2 - ax) * (by - ay)) / 2
    perim = (np.hypot(bx - ax, by - ay) + np.hypot(cx2 - bx, cy2 - by) + np.hypot(ax - cx2, ay - cy2))
    k = np.ceil(area * 5 + perim * 1.5).astype(np.int64) + 3  # dense enough for big faces *and* slivers
    if k.sum() > MAX_SAMPLES:
        k = np.maximum(3, (k * (MAX_SAMPLES / k.sum())).astype(np.int64))
    idx = np.repeat(np.arange(len(tris)), k)
    rng = np.random.default_rng(1)
    u, v = rng.random(len(idx)), rng.random(len(idx))
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    # include exact vertices too (sharp corners)
    px = ax[idx] + u * (bx[idx] - ax[idx]) + v * (cx2[idx] - ax[idx])
    py = ay[idx] + u * (by[idx] - ay[idx]) + v * (cy2[idx] - ay[idx])
    pz = az[idx] + u * (bz[idx] - az[idx]) + v * (cz[idx] - az[idx])
    ix, iy = px.astype(np.int64), py.astype(np.int64)
    ok = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
    ix, iy, pz, idx = ix[ok], iy[ok], pz[ok], idx[ok]
    pix = iy * W + ix
    order = np.lexsort((-pz, pix))  # per pixel: nearest (largest pz) first
    pix_s = pix[order]
    first = np.ones(len(pix_s), dtype=bool)
    first[1:] = pix_s[1:] != pix_s[:-1]
    win = order[first]
    tri_buf = np.full(W * H, -1, dtype=np.int64)
    depth = np.full(W * H, -1e12)
    tri_buf[pix[win]] = idx[win]
    depth[pix[win]] = pz[win]
    tri_buf, depth = tri_buf.reshape(H, W), depth.reshape(H, W)

    # fill single-pixel holes from sampling
    for _ in range(3):
        empty = tri_buf < 0
        nb_t = np.stack([np.roll(tri_buf, s, a) for a in (0, 1) for s in (1, -1)])
        nb_d = np.stack([np.roll(depth, s, a) for a in (0, 1) for s in (1, -1)])
        cnt = (nb_t >= 0).sum(0)
        best = np.argmax(nb_d, axis=0)
        fill = empty & (cnt >= 2)
        tri_buf[fill] = np.take_along_axis(nb_t, best[None], 0)[0][fill]
        depth[fill] = np.take_along_axis(nb_d, best[None], 0)[0][fill]

    # pixels where a *deeper* surface shows through because the front surface was missed by the sampling
    thr_d = max(span * 0.01, 0.2)
    for _ in range(2):
        nb_t = np.stack([np.roll(tri_buf, s, a) for a in (0, 1) for s in (1, -1)])
        nb_d = np.stack([np.roll(depth, s, a) for a in (0, 1) for s in (1, -1)])
        nearer = (nb_d > depth[None] + thr_d) & (nb_t >= 0)
        fix = nearer.sum(0) >= 3
        best = np.argmax(nb_d, axis=0)
        tri_buf[fix] = np.take_along_axis(nb_t, best[None], 0)[0][fix]
        depth[fix] = np.take_along_axis(nb_d, best[None], 0)[0][fix]

    hit = tri_buf >= 0
    n = normals[np.clip(tri_buf, 0, None)]
    n = np.where((n @ cam)[..., None] < 0, -n, n)  # two-sided
    key = cam * 0.55 + up * 0.55 - right * 0.35
    key /= np.linalg.norm(key)
    lam = 0.38 + 0.42 * np.clip(n @ cam, 0, 1) + 0.28 * np.clip(n @ key, 0, 1)
    img = colors[np.clip(tri_buf, 0, None)] * lam[..., None]
    # outlines: depth jumps (silhouettes) and creases (normal changes)
    edge = np.zeros((H, W), dtype=bool)
    thr = max(span * 0.012, 0.25)
    for a in (0, 1):
        for s in (1, -1):
            d2 = np.roll(depth, s, a)
            n2 = np.roll(n, s, a)
            h2 = np.roll(hit, s, a)
            edge |= hit & (~h2 | (np.abs(depth - d2) > thr) | ((n * n2).sum(-1) < 0.82))
    img[edge] *= 0.45
    img[~hit] = BG
    return np.clip(img, 0, 255).astype(np.uint8)


def _font(size: int):
    for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_png(proj: Project, view: str = "grid", parts: list[str] | None = None, size: int = 1000) -> tuple[bytes, list[str]]:
    """view: one of VIEWS, or 'grid' (iso / front / top / right in 2x2)."""
    items, errors = _collect(proj, parts)
    if not items:
        raise ValueError("Nothing to render" + (": " + "; ".join(errors) if errors else ""))
    tris = np.vstack([V[F] for _, V, F in items]).astype(np.float64)
    cols = np.vstack([np.repeat(_hex(s["color"])[None], len(F), 0) for s, _, F in items])
    light = cols.mean(1) > 225  # white filament: tint slightly so it reads on the light background
    cols[light] *= 0.9
    nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    allv = tris.reshape(-1, 3)
    lo, hi = allv.min(0), allv.max(0)
    sz = hi - lo

    names = ["iso", "front", "top", "right"] if view == "grid" else [view if view in VIEWS else "iso"]
    cell = size // 2 if len(names) > 1 else size
    canvas = Image.new("RGB", (cell * (2 if len(names) > 1 else 1), cell * (2 if len(names) > 1 else 1) + 34),
                       tuple(int(c) for c in BG))
    draw = ImageDraw.Draw(canvas)
    f_small, f_big = _font(14), _font(17)
    for i, nm in enumerate(names):
        e, a = VIEWS[nm]
        arr = _render_view(tris, cols, nrm, e, a, cell, cell, lo, hi)
        x0, y0 = (i % 2) * cell, 34 + (i // 2) * cell
        canvas.paste(Image.fromarray(arr), (x0, y0))
        draw.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], outline=(210, 214, 220))
        draw.text((x0 + 8, y0 + 6), nm, fill=(90, 96, 106), font=f_small)
        _axes(draw, e, a, x0 + 30, y0 + cell - 30, f_small)
    title = f"{proj.name}   {sz[0]:.1f} × {sz[1]:.1f} × {sz[2]:.1f} mm   ({len(items)} part{'s' if len(items) != 1 else ''})"
    draw.text((10, 8), title, fill=(30, 33, 38), font=f_big)
    if errors:
        draw.text((10, canvas.height - 22), "ERROR: " + "; ".join(errors)[:150], fill=(200, 30, 40), font=f_small)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), errors


def _axes(draw, elev, azim, x, y, font):
    """Small XYZ triad (X red, Y green, Z blue) so orientation is unambiguous."""
    right, up, _ = _basis(elev, azim)
    for vec, col, lab in (((1, 0, 0), (215, 40, 40), "X"), ((0, 1, 0), (40, 160, 60), "Y"), ((0, 0, 1), (40, 90, 220), "Z")):
        v = np.array(vec, dtype=float)
        dx, dy = v @ right * 20, -(v @ up) * 20
        if abs(dx) + abs(dy) < 2:
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], outline=col)
            draw.text((x + 4, y + 2), lab, fill=col, font=font)
            continue
        draw.line([x, y, x + dx, y + dy], fill=col, width=2)
        draw.text((x + dx * 1.25 - 4, y + dy * 1.25 - 7), lab, fill=col, font=font)


def thumbnail(proj: Project) -> bytes | None:
    try:
        png, _ = render_png(proj, view="iso", size=400)
        return png
    except Exception:
        return None
