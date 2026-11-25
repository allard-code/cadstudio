# SPDX-License-Identifier: GPL-3.0-or-later
"""Off-screen preview renderer so Claude can *see* what it modelled.

Pure numpy z-buffer renderer (orthographic): triangles are densely point-sampled, depth-tested per pixel,
Lambert-shaded and outlined at silhouette/crease edges. No OpenGL needed, works headless on any OS.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .project import PART_DEFAULTS, Project, plate_origin

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


def _collect(proj: Project, parts: list[str] | None, plate: int | None = None):
    """Parts to draw. With several plates and no plate filter, each part is shifted to its plate's spot in
    the plate grid (as in the editor and the slicer), so parts on different plates don't overlap."""
    items, errors = [], []
    count = proj.plate_count
    for p in proj.parts:
        s = {**PART_DEFAULTS, **p}
        if parts and s["name"] not in parts:
            continue
        if plate is not None and int(s["plate"]) != int(plate):
            continue
        if not parts and not s["visible"]:
            continue
        e = proj.build(s["name"])
        if not e["info"].get("ok"):
            errors.append(f"{s['name']}: {e['info'].get('error')}")
            continue
        V, F = e["mesh"]
        if plate is None and count > 1:
            ox, oy = plate_origin(int(s["plate"]), count)
            V = V + np.array([ox, oy, 0.0])
        items.append((s, V, F))
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
                 W: int, H: int, lo: np.ndarray, hi: np.ndarray, overhang: np.ndarray | None = None,
                 cap_color: np.ndarray | None = None, with_depth: bool = False):
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
    back = (n @ cam) < 0  # looking at the inside of a solid: only possible where a section cut it open
    n = np.where(back[..., None], -n, n)  # two-sided
    key = cam * 0.55 + up * 0.55 - right * 0.35
    key /= np.linalg.norm(key)
    lam = 0.38 + 0.42 * np.clip(n @ cam, 0, 1) + 0.28 * np.clip(n @ key, 0, 1)
    img = colors[np.clip(tri_buf, 0, None)] * lam[..., None]
    if overhang is not None:
        ov = hit & overhang[np.clip(tri_buf, 0, None)]
        warn = np.array([255, 110, 15], dtype=np.float32)  # orange: unsupported overhang
        img = np.where(ov[..., None], img * 0.3 + warn * 0.7, img)
    # outlines: depth jumps (silhouettes) and creases (normal changes)
    edge = np.zeros((H, W), dtype=bool)
    thr = max(span * 0.012, 0.25)
    for a in (0, 1):
        for s in (1, -1):
            d2 = np.roll(depth, s, a)
            n2 = np.roll(n, s, a)
            h2 = np.roll(hit, s, a)
            edge |= hit & (~h2 | (np.abs(depth - d2) > thr) | ((n * n2).sum(-1) < 0.82))
    if cap_color is not None:  # cut faces of a section: flat colour so the solid material reads as cut
        img = np.where((hit & back)[..., None], cap_color * (0.8 + 0.2 * lam[..., None]), img)
    img[edge] *= 0.45
    img[~hit] = BG
    out = np.clip(img, 0, 255).astype(np.uint8)
    if with_depth:
        return out, np.where(hit, depth, -np.inf), edge
    return out


def _font(size: int):
    for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_png(proj: Project, view: str = "grid", parts: list[str] | None = None, size: int = 1000,
              overhangs: bool = False, overhang_angle: float = 45.0,
              plate: int | None = None) -> tuple[bytes, list[str]]:
    """view: one of VIEWS, or 'grid' (iso / front / top / right in 2x2).
    overhangs: tint faces that need support orange - downward-facing faces steeper than overhang_angle
    (degrees, measured from a vertical wall; 0 = never needs support, 90 = flags any downward-facing slope),
    excluding faces resting on the bed itself.
    plate: only parts on that build plate (default: all plates, laid out side by side)."""
    items, errors = _collect(proj, parts, plate)
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

    overhang = None
    if overhangs:
        # downward-facing steeper than the threshold: |n.z| > cos(angle from vertical), n.z < 0
        thresh = math.cos(math.radians(max(0.0, min(90.0, overhang_angle))))
        tri_min_z = tris[:, :, 2].min(axis=1)
        on_bed = tri_min_z <= 0.05  # resting on the build plate (world z=0), not actually unsupported
        overhang = (nrm[:, 2] < -thresh) & ~on_bed

    names = ["iso", "front", "top", "right"] if view == "grid" else [view if view in VIEWS else "iso"]
    cell = size // 2 if len(names) > 1 else size
    canvas = Image.new("RGB", (cell * (2 if len(names) > 1 else 1), cell * (2 if len(names) > 1 else 1) + 34),
                       tuple(int(c) for c in BG))
    draw = ImageDraw.Draw(canvas)
    f_small, f_big = _font(14), _font(17)
    for i, nm in enumerate(names):
        e, a = VIEWS[nm]
        arr = _render_view(tris, cols, nrm, e, a, cell, cell, lo, hi, overhang=overhang)
        x0, y0 = (i % 2) * cell, 34 + (i // 2) * cell
        canvas.paste(Image.fromarray(arr), (x0, y0))
        draw.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], outline=(210, 214, 220))
        draw.text((x0 + 8, y0 + 6), nm, fill=(90, 96, 106), font=f_small)
        _axes(draw, e, a, x0 + 30, y0 + cell - 30, f_small)
    where = f"  plate {plate}/{proj.plate_count}" if plate is not None else (
        f"  {proj.plate_count} plates" if proj.plate_count > 1 else "")
    n_parts = f"{len(items)} part{'s' if len(items) != 1 else ''}"
    title = f"{proj.name}{where}   {sz[0]:.1f} × {sz[1]:.1f} × {sz[2]:.1f} mm   ({n_parts})"
    if overhangs:
        title += f"   [orange = overhang >{overhang_angle:.0f}°, needs support]"
    draw.text((10, 8), title, fill=(30, 33, 38), font=f_big)
    if errors:
        draw.text((10, canvas.height - 22), "ERROR: " + "; ".join(errors)[:150], fill=(200, 30, 40), font=f_small)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), errors


# --------------------------------------------------------------------------- assembly view

SECTION_COLOR = np.array([214, 64, 64], dtype=np.float32)
AXES = {"x": 0, "y": 1, "z": 2}


def clip_triangles(tris: np.ndarray, axis: int, at: float, keep_above: bool = False) -> np.ndarray:
    """Cut triangles (N, 3, 3) with the plane coord[axis] = at and keep one side (default: coord <= at).
    Triangles crossing the plane are split, so the cut edge is exact (no jagged gaps on big faces)."""
    d = tris[:, :, axis] - at
    if keep_above:
        d = -d
    inside = d <= 0
    cnt = inside.sum(1)
    out = [tris[cnt == 3]]
    for k in np.nonzero((cnt == 1) | (cnt == 2))[0]:
        poly = []
        for i in range(3):
            a, b = tris[k, i], tris[k, (i + 1) % 3]
            da, db = d[k, i], d[k, (i + 1) % 3]
            if da <= 0:
                poly.append(a)
            if (da <= 0) != (db <= 0):
                poly.append(a + (b - a) * (da / (da - db)))
        for j in range(1, len(poly) - 1):  # fan; keeps the original winding (outward normal)
            out.append(np.array([[poly[0], poly[j], poly[j + 1]]]))
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def _explode_offsets(boxes: list[tuple[np.ndarray, np.ndarray]], specs: list[dict], factor: float) -> list[np.ndarray]:
    if not factor:
        return [np.zeros(3) for _ in boxes]
    lo = np.min([b[0] for b in boxes], axis=0)
    hi = np.max([b[1] for b in boxes], axis=0)
    centre = (lo + hi) / 2
    out = []
    for (blo, bhi), s in zip(boxes, specs):
        v = np.array(s["explode"], dtype=float) if s.get("explode") else (blo + bhi) / 2 - centre
        out.append(v * factor)
    return out


def render_assembly_png(proj: Project, view: str = "iso", size: int = 1000, items: list[str] | None = None,
                        hide: list[str] | None = None, ghost: list[str] | None = None, explode: float = 0.0,
                        section: str | None = None, section_at: float | None = None,
                        section_flip: bool = False) -> tuple[bytes, list[str]]:
    """Picture of the assembly (how the printed parts go together).
    view: one of VIEWS or 'grid'. items: only these items (default: all visible). hide: leave these out.
    ghost: draw these see-through (default: the items marked ghost) - e.g. the body shell, to show what's inside.
    explode: move items apart (0 = assembled, 1 = each item twice as far from the centre, or by its own
    `explode` vector). section: 'x' | 'y' | 'z' cuts the assembly at section_at (mm, default the middle) and
    removes the half facing the viewer (section_flip: the other half); cut faces are drawn red."""
    errors, specs, meshes = [], [], []
    for s in proj.assembly_specs():
        if items and s["name"] not in items:
            continue
        if not items and not s["visible"]:
            continue
        if hide and s["name"] in hide:
            continue
        e = proj.build_assembly_item(s["name"])
        if not e["info"].get("ok"):
            errors.append(f"{s['name']}: {e['info'].get('error')}")
            continue
        specs.append(s)
        meshes.append(e["mesh"])
    if not specs:
        raise ValueError("Nothing to render: the assembly is empty" + (" (" + "; ".join(errors) + ")" if errors else
                         " - add items with set_assembly_item()"))
    ghosts = set(ghost) if ghost is not None else {s["name"] for s in specs if s["ghost"]}
    boxes = [(V.min(0), V.max(0)) for V, _ in meshes]
    offs = _explode_offsets(boxes, specs, explode)
    tris_all = [(V + o)[F] for (V, F), o in zip(meshes, offs)]
    axis = AXES.get((section or "").lower()) if section else None
    if section and axis is None:
        raise ValueError("section must be 'x', 'y' or 'z'")
    allv = np.vstack([t.reshape(-1, 3) for t in tris_all])
    lo, hi = allv.min(0), allv.max(0)  # framing from the whole assembly: same scale with or without a section
    at = None
    if axis is not None:
        at = section_at if section_at is not None else float((lo[axis] + hi[axis]) / 2)
    cap = SECTION_COLOR if axis is not None else None

    def layer(tris_list, sel):
        tt = [(t, s) for t, s in zip(tris_list, specs) if sel(s) and len(t)]
        if not tt:
            return None
        tris = np.vstack([t for t, _ in tt]).astype(np.float64)
        cols = np.vstack([np.repeat(_hex(s["color"])[None], len(t), 0) for t, s in tt])
        nrm = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
        return tris, cols, nrm
    names = ["iso", "front", "top", "right"] if view == "grid" else [view if view in VIEWS else "iso"]
    cell = size // 2 if len(names) > 1 else size
    canvas = Image.new("RGB", (cell * (2 if len(names) > 1 else 1), cell * (2 if len(names) > 1 else 1) + 34),
                       tuple(int(c) for c in BG))
    draw = ImageDraw.Draw(canvas)
    f_small, f_big = _font(14), _font(17)
    for i, nm in enumerate(names):
        e, az = VIEWS[nm]
        view_tris = tris_all
        if axis is not None:  # cut away the half facing the viewer (section_flip: the other half)
            cam = _basis(e, az)[2]
            keep_above = bool((cam[axis] < 0) != section_flip)
            view_tris = [clip_triangles(t, axis, at, keep_above=keep_above) for t in tris_all]
        solid = layer(view_tris, lambda s: s["name"] not in ghosts)
        see = layer(view_tris, lambda s: s["name"] in ghosts)
        if solid is not None:
            arr, dep, _ = _render_view(*solid, e, az, cell, cell, lo, hi, cap_color=cap, with_depth=True)
        else:
            arr, dep = np.full((cell, cell, 3), BG, dtype=np.uint8), np.full((cell, cell), -np.inf)
        if see is not None:
            g, gdep, gedge = _render_view(*see, e, az, cell, cell, lo, hi, cap_color=cap, with_depth=True)
            front = np.isfinite(gdep) & (gdep >= dep - 1e-6)
            mix = arr.astype(np.float32)
            mix[front] = mix[front] * 0.7 + g[front].astype(np.float32) * 0.3
            outline = front & gedge
            mix[outline] = mix[outline] * 0.55 + g[outline].astype(np.float32) * 0.45
            arr = np.clip(mix, 0, 255).astype(np.uint8)
        x0, y0 = (i % 2) * cell, 34 + (i // 2) * cell
        canvas.paste(Image.fromarray(arr), (x0, y0))
        draw.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], outline=(210, 214, 220))
        draw.text((x0 + 8, y0 + 6), nm, fill=(90, 96, 106), font=f_small)
        _axes(draw, e, az, x0 + 30, y0 + cell - 30, f_small)
    sz = hi - lo
    title = f"{proj.name}  assembly   {sz[0]:.1f} × {sz[1]:.1f} × {sz[2]:.1f} mm   ({len(specs)} items)"
    extra = []
    if ghosts & {s["name"] for s in specs}:
        extra.append("see-through: " + ", ".join(s["name"] for s in specs if s["name"] in ghosts))
    if explode:
        extra.append(f"exploded ×{explode:g}")
    if axis is not None:
        extra.append(f"section {section.lower()}={at:.1f}")
    if extra:
        title += "   [" + "; ".join(extra) + "]"
    draw.text((10, 8), title[:160], fill=(30, 33, 38), font=f_big)
    if errors:
        draw.text((10, canvas.height - 22), "ERROR: " + "; ".join(errors)[:150], fill=(200, 30, 40), font=f_small)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), errors


def save_assembly_png(proj: Project, png: bytes, view: str = "iso", filename: str | None = None) -> Path:
    """Write an assembly picture to <project>/exports/ (default <project>-assembly-<view>.png)."""
    out = Path(filename) if filename else proj.dir / "exports" / f"{proj.name}-assembly-{view}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    return out


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


def thin_wall_mask(V: np.ndarray, F: np.ndarray, threshold_mm: float = 1.2,
                   max_dist_mm: float = 50.0) -> tuple[np.ndarray, np.ndarray]:
    """Per-face local wall thickness (mm), by casting a ray from each face into the solid along its inward
    normal to the first opposite-facing wall. Returns (thickness, thin) where thin flags thickness <
    threshold_mm (default 1.2 mm, about 3 perimeter lines at a 0.4 mm nozzle). A face with no hit within
    max_dist_mm (e.g. the outside of a big solid block) gets thickness = inf, never flagged.
    Only a heuristic (nearest ray hit, not true local thickness) - a sharp near-tangent surface or a
    non-watertight mesh can give false positives/negatives. Needs the `rtree` package for speed; see
    mesh_boolean() for the similar watertightness caveat."""
    import trimesh

    mesh = trimesh.Trimesh(vertices=V, faces=F, process=False)
    normals = mesh.face_normals
    centroids = mesh.triangles_center
    eps = 1e-4 * max(1.0, float(np.ptp(V, axis=0).max()))  # nudge inward, scaled to the model's own size
    origins = centroids - normals * eps
    directions = -normals
    thickness = np.full(len(F), np.inf)
    try:
        locs, idx_ray, _ = mesh.ray.intersects_location(origins, directions)
    except Exception:
        return thickness, np.zeros(len(F), dtype=bool)
    if len(idx_ray):
        d = np.linalg.norm(locs - origins[idx_ray], axis=1)
        order = np.lexsort((d, idx_ray))  # per ray: nearest hit first
        ir, ds = idx_ray[order], d[order]
        first = np.ones(len(ir), dtype=bool)
        first[1:] = ir[1:] != ir[:-1]
        thickness[ir[first]] = ds[first]
    thickness[thickness > max_dist_mm] = np.inf
    return thickness, thickness < threshold_mm


def thumbnail(proj: Project) -> bytes | None:
    try:
        png, _ = render_png(proj, view="iso", size=400)
        return png
    except Exception:
        return None
