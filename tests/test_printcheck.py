# SPDX-License-Identifier: GPL-3.0-or-later
import build123d as bd

from cadstudio.printcheck import find_floating
from cadstudio.project import tessellate

MIN = (bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)


def _islands(shape, **kw):
    V, F = tessellate(shape)
    return find_floating([("p", V, F)], **kw)


def test_block_on_bed_has_no_floating_regions():
    assert _islands(bd.Box(20, 10, 5, align=MIN)) == []


def test_attached_overhang_and_bridge_are_not_floating():
    # a T: a 30 mm wide slab on top of a 6 mm post (big overhang, but attached to the post)
    t = bd.Box(6, 6, 10, align=MIN) + bd.Pos(0, 0, 10) * bd.Box(30, 10, 2, align=MIN)
    assert _islands(t) == []
    # an arch: a bridge between two pillars
    arch = (bd.Pos(-10, 0, 0) * bd.Box(4, 6, 8, align=MIN) + bd.Pos(10, 0, 0) * bd.Box(4, 6, 8, align=MIN)
            + bd.Pos(0, 0, 8) * bd.Box(24, 6, 2, align=MIN))
    assert _islands(arch) == []


def test_cylinder_starting_inside_a_hollow_body_is_floating():
    # hollow box (ceiling from z=18.4 to 20) with a "chimney" that starts at z=15, below the ceiling
    outer = bd.Box(30, 30, 20, align=MIN)
    inner = bd.Pos(0, 0, -1) * bd.Box(26.8, 26.8, 19.4, align=MIN)
    chimney = bd.Pos(0, 0, 15) * bd.Cylinder(4, 10, align=MIN)
    found = _islands(outer - inner + chimney)
    assert len(found) == 1
    isl = found[0]
    assert abs(isl["z_mm"] - 15.0) <= 0.2
    assert abs(isl["area_mm2"] - 3.1416 * 16) < 4          # the chimney's cross-section
    assert abs(isl["center"][0]) < 0.5 and abs(isl["center"][1]) < 0.5
    # starting the chimney on the ceiling fixes it
    fixed = outer - inner + bd.Pos(0, 0, 18.4) * bd.Cylinder(4, 7, align=MIN)
    assert _islands(fixed) == []


def test_part_above_the_bed_is_reported_at_its_lowest_layer():
    found = _islands(bd.Pos(0, 0, 5) * bd.Box(10, 10, 4, align=MIN))
    assert len(found) == 1 and abs(found[0]["z_mm"] - 5.0) <= 0.2


def test_parts_on_the_same_plate_support_each_other():
    base = bd.Box(20, 20, 3, align=MIN)
    stacked = bd.Pos(0, 0, 3) * bd.Box(8, 8, 2, align=MIN)     # e.g. a second colour sitting on the base
    Vb, Fb = tessellate(base)
    Vs, Fs = tessellate(stacked)
    assert find_floating([("base", Vb, Fb), ("top", Vs, Fs)]) == []
    found = find_floating([("top", Vs, Fs)])                   # without the base it floats
    assert found and found[0]["part"] == "top"
