# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from cadstudio import lib
from cadstudio.fitcheck import check_fit
from cadstudio.printcheck import find_bridges


def _mesh(proj, name, code):
    proj.upsert_part(name, code=code)
    e = proj.build(name)
    assert e["info"]["ok"], e["info"]
    V, F = e["mesh"]
    return (name, V, F)


# ---------------------------------------------------------------- bridges

HOOD = ("outer = Box(40, 60, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
        "inner = Pos(0, 0, -1) * Box(36, 56, 19, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
        "result = outer - inner")


def test_flat_ceiling_is_a_bridge_across_the_short_side(proj):
    r = find_bridges([_mesh(proj, "hood", HOOD)], max_bridge_mm=20)
    assert r["longest_bridge"]["hood"] == pytest.approx(36, abs=0.6)
    [issue] = r["issues"]
    assert issue["kind"] == "bridge" and issue["z_mm"] == pytest.approx(18, abs=0.3)


def test_chamfered_ceiling_shortens_the_bridge(proj):
    code = HOOD.replace("result = outer - inner",
                        "inner = chamfer(inner.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1], length=12)\n"
                        "result = outer - inner")
    r = find_bridges([_mesh(proj, "hood2", code)], max_bridge_mm=20)
    assert r["longest_bridge"]["hood2"] == pytest.approx(12, abs=1.0)
    assert r["issues"] == []


def test_ledge_is_an_overhang(proj):
    code = ("result = Box(20, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))"
            " + Pos(0, 0, 10) * Box(26, 20, 2, align=(Align.CENTER, Align.CENTER, Align.MIN))")
    r = find_bridges([_mesh(proj, "ledge", code)], max_overhang_mm=1.0)
    assert len(r["issues"]) == 2  # one ledge on each side
    for issue in r["issues"]:
        assert issue["kind"] == "overhang" and issue["span_mm"] == pytest.approx(3.0, abs=0.3)


def test_check_bridges_tool(proj):
    from cadstudio.mcp_server import check_bridges

    proj.upsert_part("hood", code=HOOD)
    res = check_bridges()
    assert res["ok"] is False and res["plates"]["1"]["longest_bridge"]["hood"] > 30


# ---------------------------------------------------------------- fit

def test_fit_check_flags_overlap_tight_and_respects_allow(proj):
    proj.upsert_assembly_item("block", code="result = Box(20, 20, 10)")
    proj.upsert_assembly_item("inside", code="result = Pos(5, 0, 0) * Box(4, 4, 4)")          # overlaps block
    proj.upsert_assembly_item("near", code="result = Pos(10.15 + 2, 0, 0) * Box(4, 4, 4)")    # 0.15 mm gap
    proj.upsert_assembly_item("far", code="result = Pos(40, 0, 0) * Box(4, 4, 4)")
    r = check_fit(proj)
    st = {(p["a"], p["b"]): p for p in r["pairs"]}
    assert st[("block", "inside")]["status"] == "overlap" and st[("block", "inside")]["overlap_mm3"] == pytest.approx(64)
    assert st[("block", "near")]["status"] == "tight"
    assert st[("block", "near")]["clearance_mm"] == pytest.approx(0.15, abs=1e-3)
    assert not any("far" in (p["a"], p["b"]) for p in r["pairs"])
    assert r["ok"] is False and r["issues"][0]["status"] == "overlap"
    r2 = check_fit(proj, allow=[["block", "ins*"], "near:block"])
    assert r2["ok"] is True and all(p["status"] == "allowed" for p in r2["pairs"])


def test_fit_check_skips_broken_items(proj):
    proj.upsert_assembly_item("ok", code="result = Box(2, 2, 2)")
    proj.upsert_assembly_item("bad", code="result = 1/0")
    r = check_fit(proj)
    assert r["skipped"][0]["item"] == "bad" and r["ok"]


# ---------------------------------------------------------------- library

def test_lib_is_available_in_part_code(proj):
    proj.upsert_part("g", code="result = spur_gear(1, 13, 3.5, bore_r=2, bore_flat=1.7)")
    proj.upsert_part("c", code="result = tolerance_coupon(2, flat_from_centre=1.7)")
    proj.upsert_part("m", code="result = Box(12, 12, 5) - Pos(0, 0, -1) * magnet_pocket(6, 3)")
    for n in "gcm":
        assert proj.build(n)["info"]["ok"], proj.build(n)["info"]


def test_own_shared_code_overrides_lib(proj):
    proj.data["common"] = "def spur_gear(*a, **k):\n    return Box(1, 1, 1)"
    proj.upsert_part("g", code="result = spur_gear(1, 13, 3.5)")
    assert proj.build("g")["info"]["volume_mm3"] == pytest.approx(1)


def test_gear_and_hole_sizes():
    assert lib.gear_centre_distance(1, 13, 28) == pytest.approx(20.65)
    g = lib.spur_gear(1, 28, 3.5, bore_r=1.5)
    assert g.bounding_box().size.X == pytest.approx(28 + 1.8, abs=0.2)
    h = lib.d_hole(2, 1.7, 10, clearance=0.2)
    bb = h.bounding_box()
    assert bb.max.X == pytest.approx(2.2) and bb.min.X == pytest.approx(-1.9)
    s = lib.d_shaft(2, 1.7, 20)
    assert s.bounding_box().min.X == pytest.approx(-1.7) and s.is_valid
    c = lib.tolerance_coupon(2, clearances=(0.1, 0.2))
    assert c.is_valid and c.bounding_box().size.Z == pytest.approx(6)
