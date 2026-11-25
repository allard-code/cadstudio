# SPDX-License-Identifier: GPL-3.0-or-later
"""Ready-made helpers for functional 3D prints, available in every part's code without importing.

All dimensions in mm; shapes are build123d Parts. Holes come out the size you ask for *plus* a clearance, because
printed holes shrink: measure your printer once with tolerance_coupon() and set the clearance from it.
"""
from __future__ import annotations

import math

import numpy as np
from build123d import (
    Align,
    Box,
    Circle,
    Cylinder,
    GeomType,
    Part,
    Plane,
    Polygon,
    Polyline,
    Pos,
    Text,
    chamfer,
    extrude,
    make_face,
)

__all__ = [
    "spur_gear", "gear_centre_distance", "d_hole", "d_shaft", "teardrop", "pin", "pin_hole", "screw_boss",
    "magnet_pocket", "tolerance_coupon",
]

_C = (Align.CENTER, Align.CENTER, Align.MIN)


def d_hole(r: float, flat_from_centre: float, h: float, clearance: float = 0.2) -> Part:
    """D-shaped hole along Z, centred on the origin, for a shaft of radius r whose flat lies flat_from_centre from
    the axis (on the -X side). clearance is added all round (vertical printed holes come out smaller)."""
    r += clearance
    flat = flat_from_centre + clearance
    return Cylinder(r, h) - Pos(-r - flat, 0, 0) * Box(2 * r, 2 * r + 2, h + 2)


def d_shaft(r: float, flat_from_centre: float, length: float, end_chamfer: float = 0.5) -> Part:
    """D-shaft along Z from z=0, flat on the -X side, with chamfered ends so it slides into a hole easily.
    Print it lying down (rotate 90 degrees about Y) with the flat on the bed."""
    s = Cylinder(r, length, align=_C)
    if end_chamfer:
        s = chamfer(s.edges().filter_by(GeomType.CIRCLE), length=end_chamfer)
    return s - Pos(-r - flat_from_centre, 0, length / 2) * Box(2 * r, 2 * r + 2, length + 2)


def teardrop(r: float, length: float, axis: str = "x", tip: str = "up") -> Part:
    """Horizontal round hole that prints without support: a circle with a 45-degree point, centred on the origin.
    axis: 'x' or 'y' (the hole's direction). tip: 'up' when the part prints this way up, 'down' for a part that
    prints upside down (the point then ends up on top while printing)."""
    s = 1 if tip == "up" else -1
    k = r * math.sqrt(0.5)
    prof = Circle(r) + Polygon((-k, s * k), (k, s * k), (0, s * r * math.sqrt(2)))
    plane = Plane.YZ if axis == "x" else Plane.XZ
    return extrude(plane * prof, amount=length / 2, both=True)


def pin(r: float, length: float, end_chamfer: float = 0.3) -> Part:
    """Round pin along Z from z=0 with a chamfered tip (top)."""
    p = Cylinder(r, length, align=_C)
    return chamfer(p.edges().filter_by(GeomType.CIRCLE).group_by()[-1], length=min(end_chamfer, r / 2))


def pin_hole(r: float, depth: float, clearance: float = 0.2, from_z: float = 0.0) -> Part:
    """Hole for pin(r): radius r + clearance, from z=from_z down to from_z - depth (subtract it)."""
    return Pos(0, 0, from_z - depth) * Cylinder(r + clearance, depth + 0.01, align=_C)


def screw_boss(outer_r: float, hole_r: float, height: float, hole_depth: float | None = None) -> Part:
    """Boss for a self-tapping screw, from z=0 up, open at the bottom. hole_r: pilot hole (M3 self-tapper in PLA:
    1.35-1.45). hole_depth defaults to height - 1.5, so 1.5 mm of material stays closed on top."""
    d = height - 1.5 if hole_depth is None else hole_depth
    return Cylinder(outer_r, height, align=_C) - Pos(0, 0, -0.01) * Cylinder(hole_r, d + 0.01, align=_C)


def magnet_pocket(d: float, h: float, clearance: float = 0.15, depth_clearance: float = 0.1) -> Part:
    """Cavity for a round magnet (diameter d, height h), axis Z, from z=0 up. Subtract it with its top at least
    0.6 mm (3 layers) below the surface to enclose the magnet completely: pause the print at the first layer
    above the cavity (slice_plate(pauses=...)), drop the magnet in and resume. A captured magnet can't come
    loose - required for toys."""
    return Cylinder(d / 2 + clearance, h + depth_clearance, align=_C)


def gear_centre_distance(module: float, teeth_a: int, teeth_b: int, clearance: float = 0.15) -> float:
    """Distance between the axes of two meshing spur_gear()s; clearance adds a little play for printed teeth."""
    return module * (teeth_a + teeth_b) / 2 + clearance


def spur_gear(module: float, teeth: int, width: float, bore_r: float | None = None,
              bore_flat: float | None = None, backlash: float = 0.1, tip: float = 0.9,
              bore_clearance: float = 0.2) -> Part:
    """Involute spur gear (20 degree pressure angle) along Z from z=0 to width.
    bore_r: shaft radius (None = no bore); bore_flat: distance from the axis to the shaft's flat for a D-shaft
    (None = round). backlash (mm on the pitch circle) and a slightly short tip (tip * module) let printed gears
    run freely. Mesh two gears at gear_centre_distance()."""
    a20 = math.radians(20)

    def inv(a):
        return math.tan(a) - a

    rp = module * teeth / 2
    rb, ra, rf = rp * math.cos(a20), rp + tip * module, rp - 1.25 * module
    half = math.pi / (2 * teeth) + inv(a20) - backlash / (2 * rp)

    def th(r):
        return half if r <= rb else half - inv(math.acos(rb / r))

    radii = ([rf] if rf < rb else []) + list(np.linspace(max(rf, rb), ra, 8))
    pts = []
    for k in range(teeth):
        ph = 2 * math.pi * k / teeth
        pts += [(r * math.cos(ph - th(r)), r * math.sin(ph - th(r))) for r in radii]
        pts += [(r * math.cos(ph + th(r)), r * math.sin(ph + th(r))) for r in reversed(radii)]
    g = extrude(make_face(Polyline(*pts, close=True)), amount=width)
    if bore_r:
        if bore_flat is None:
            g -= Pos(0, 0, width / 2) * Cylinder(bore_r + bore_clearance, width * 3)
        else:
            g -= Pos(0, 0, width / 2) * d_hole(bore_r, bore_flat, width * 3, bore_clearance)
    return g


def tolerance_coupon(r: float, clearances=(0.1, 0.15, 0.2, 0.25, 0.3), flat_from_centre: float | None = None,
                     depth: float = 6.0, label: bool = True) -> Part:
    """Small test print to measure the clearance your printer needs: one hole per clearance in a strip,
    for a shaft of radius r (D-shaped when flat_from_centre is given), with the clearance engraved next to it.
    Print it, try your shaft/pin in each hole and use the best fitting value as the clearance in your design."""
    pitch = 2 * (r + max(clearances)) + 5
    n = len(clearances)
    w, length = r * 2 + 10, pitch * n + 2
    plate = Box(length, w, depth, align=_C)
    plate = chamfer(plate.edges().group_by()[-1], length=0.4)
    for i, c in enumerate(clearances):
        x = -length / 2 + 1 + pitch * (i + 0.5)
        hole = (Cylinder(r + c, depth * 3) if flat_from_centre is None
                else d_hole(r, flat_from_centre, depth * 3, c))
        plate -= Pos(x, -1.5, depth / 2) * hole
        if label:
            txt = Text(f"{c:.2f}".lstrip("0"), font_size=3.2, align=(Align.CENTER, Align.CENTER))
            plate -= Pos(x, w / 2 - 2.6, depth - 0.6) * extrude(txt, amount=1)
    return plate
