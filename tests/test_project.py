# SPDX-License-Identifier: GPL-3.0-or-later
import math

import numpy as np
import pytest
import trimesh

from cadstudio import project as P

from .conftest import BOX


def test_box_builds_with_correct_size(proj):
    proj.upsert_part("a", code=BOX)
    info = proj.build("a")["info"]
    assert info["ok"], info
    assert info["size"] == [20.0, 10.0, 5.0]
    assert info["bbox_min"][2] == 0.0
    assert abs(info["volume_mm3"] - 1000) < 1e-6
    assert info["watertight"] is True


def test_user_errors_are_reported_not_raised(proj):
    proj.upsert_part("bad", code="result = Box(1, 2)")
    info = proj.build("bad")["info"]
    assert info["ok"] is False
    assert "TypeError" in info["error"]
    proj.upsert_part("empty", code="x = 1")
    assert "result" in proj.build("empty")["info"]["error"]
    proj.upsert_part("flat", code="result = Rectangle(5, 5)")
    assert proj.build("flat")["info"]["ok"] is False


def test_parameters_drive_geometry(proj):
    proj.set_params({"w": 30})
    proj.upsert_part("a", code="result = Box(w, 10, 5)")
    assert proj.build("a")["info"]["size"][0] == 30
    proj.set_params({"w": 45})
    assert proj.build("a")["info"]["size"][0] == 45


def test_part_reference_inlay_and_rename(proj):
    proj.upsert_part("body", code="result = Box(20, 20, 10) - part('pin')")
    proj.upsert_part("pin", code="result = Cylinder(2, 10)")
    body, pin = proj.build("body")["info"], proj.build("pin")["info"]
    assert body["ok"] and pin["ok"]
    assert abs(body["volume_mm3"] + pin["volume_mm3"] - 4000) < 0.5  # volumes don't overlap
    proj.rename_part("pin", "peg")
    assert "part(\"peg\")" in proj.find("body")["code"]
    assert proj.build("body")["info"]["ok"]


def test_circular_reference_is_detected(proj):
    proj.upsert_part("a", code="result = part('b')")
    proj.upsert_part("b", code="result = part('a')")
    assert "Circular" in proj.build("a")["info"]["error"]


def test_location_is_applied(proj):
    proj.upsert_part("a", code=BOX, location=[10, 0, 5, 0, 0, 90])
    info = proj.build("a")["info"]
    assert info["size"] == [10.0, 20.0, 5.0]
    assert info["bbox_min"] == [5.0, -10.0, 5.0]


def test_scale_stretches_about_its_own_centre(proj):
    proj.upsert_part("a", code=BOX, scale=[2, 1, 1])
    info = proj.build("a")["info"]
    assert info["size"] == [40.0, 10.0, 5.0]
    assert info["bbox_min"] == [-20.0, -5.0, 0.0]
    assert abs(info["volume_mm3"] - 2000) < 1e-6


def test_scale_combines_with_location(proj):
    proj.upsert_part("a", code=BOX, scale=[2, 1, 1], location=[10, 0, 0, 0, 0, 0])
    info = proj.build("a")["info"]
    assert info["size"] == [40.0, 10.0, 5.0]
    assert info["bbox_min"] == [-10.0, -5.0, 0.0]  # stretched first, then moved


def test_scale_is_clamped_to_positive(proj):
    proj.upsert_part("a", code=BOX, scale=[-5, 0, 3])
    assert proj.find("a")["scale"] == [0.01, 0.01, 3.0]


def test_common_code_is_shared_across_parts(proj):
    proj.data["common"] = "def slab(l, w, h): return Box(l, w, h)"
    proj.upsert_part("a", code="result = slab(20, 10, 5)")
    proj.upsert_part("b", code="result = slab(8, 8, 8)")
    assert proj.build("a")["info"]["size"] == [20.0, 10.0, 5.0]
    assert proj.build("b")["info"]["size"] == [8.0, 8.0, 8.0]


def test_common_code_can_use_part_ref(proj):
    proj.data["common"] = "def doubled(name): return part(name) + Pos(0, 0, 100) * part(name)"
    proj.upsert_part("base", code=BOX)
    proj.upsert_part("a", code="result = doubled('base')")
    assert abs(proj.build("a")["info"]["volume_mm3"] - 2000) < 1e-6


def test_common_code_change_invalidates_cache(proj):
    proj.data["common"] = "def slab(): return Box(10, 10, 5)"
    proj.upsert_part("a", code="result = slab()")
    assert proj.build("a")["info"]["size"] == [10.0, 10.0, 5.0]
    proj.data["common"] = "def slab(): return Box(20, 10, 5)"
    proj.save()
    assert proj.build("a")["info"]["size"] == [20.0, 10.0, 5.0]


def test_common_code_error_is_reported_not_raised(proj):
    proj.data["common"] = "this is not valid python ("
    proj.upsert_part("a", code=BOX)
    info = proj.build("a")["info"]
    assert info["ok"] is False
    assert "SyntaxError" in info["error"]


def test_presets_save_and_apply(proj):
    proj.set_params({"w": 10, "h": 5})
    proj.save_preset("small")
    proj.set_params({"w": 40, "h": 20}, replace=True)
    proj.save_preset("large")
    assert proj.apply_preset("small") == {"w": 10, "h": 5}
    assert proj.params == {"w": 10, "h": 5}
    assert proj.apply_preset("large") == {"w": 40, "h": 20}
    assert set(proj.summary()["presets"]) == {"small", "large"}


def test_apply_unknown_preset_raises(proj):
    with pytest.raises(P.PartError, match="does not exist"):
        proj.apply_preset("nope")


def test_array_part_creates_grid_with_default_spacing(proj):
    proj.upsert_part("clip", code=BOX)  # 20 x 10 x 5, margin default 3 -> spacing 23 x 13
    res = proj.array_part("clip", count_x=3, count_y=2)
    assert res["parts"] == ["clip", "clip_1_0", "clip_2_0", "clip_0_1", "clip_1_1", "clip_2_1"]
    assert res["fits_bed"] is True
    assert res["bed_footprint"] == [66.0, 23.0]
    assert proj.find("clip_2_1")["location"][:2] == [46.0, 13.0]
    assert proj.find("clip_1_0")["location"][:2] == [23.0, 0.0]
    # copies are independent parts with their own geometry, not references
    assert proj.build("clip_2_1")["info"]["ok"]


def test_array_part_respects_explicit_spacing_and_existing_location(proj):
    proj.upsert_part("base", code=BOX, location=[5, 5, 0, 0, 0, 0])
    res = proj.array_part("base", count_x=2, count_y=1, spacing_x=50)
    assert proj.find("base_1_0")["location"][:3] == [55.0, 5.0, 0.0]
    assert res["bed_footprint"][0] == 70.0  # (2-1)*50 + 20


def test_array_part_avoids_name_collisions(proj):
    proj.upsert_part("clip", code=BOX)
    proj.upsert_part("clip_1_0", code=BOX)  # pre-existing name that would collide
    res = proj.array_part("clip", count_x=2, count_y=1)
    assert "clip_1_0_1" in res["parts"]


def test_array_part_rejects_too_many_copies(proj):
    proj.upsert_part("clip", code=BOX)
    with pytest.raises(P.PartError, match="more than 200"):
        proj.array_part("clip", count_x=20, count_y=11)


def test_array_part_rejects_zero_count(proj):
    proj.upsert_part("clip", code=BOX)
    with pytest.raises(P.PartError, match="at least 1"):
        proj.array_part("clip", count_x=0)


def test_array_part_rejects_broken_part(proj):
    proj.upsert_part("bad", code="result = Box(1, 2)")
    with pytest.raises(P.PartError, match="doesn't build ok"):
        proj.array_part("bad", count_x=2)


def test_delete_preset(proj):
    proj.set_params({"w": 10})
    proj.save_preset("small")
    proj.delete_preset("small")
    assert "small" not in proj.presets
    with pytest.raises(P.PartError):
        proj.delete_preset("small")


def test_filament_auto_assignment(proj):
    proj.upsert_part("a", code=BOX, color="#ff0000")
    proj.upsert_part("b", code=BOX, color="#00ff00")
    proj.upsert_part("c", code=BOX, color="#ff0000")
    assert [proj.find(n)["filament"] for n in "abc"] == [1, 2, 1]


def test_weld_makes_watertight():
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0], [1, 0, 0], [0, 0, 1.0]])
    F = np.array([[0, 1, 2], [3, 4, 5]])
    V2, F2 = P.weld(V, F)
    assert len(V2) == 4 and F2.max() == 3


def test_mesh_import_is_recentred(proj, tmp_path):
    f = tmp_path / "cube.stl"
    trimesh.creation.box((10, 10, 10)).apply_translation((100, 100, 100)).export(f)
    proj.import_mesh("ref", f)
    info = proj.build("ref")["info"]
    assert info["ok"] and info["bbox_min"] == [-5.0, -5.0, 0.0]
    assert abs(info["volume_mm3"] - 1000) < 1e-6


def test_mesh_boolean_subtract_with_imported_mesh(proj, tmp_path):
    f = tmp_path / "cube.stl"
    trimesh.creation.box((10, 10, 10)).export(f)
    proj.import_mesh("ref", f)
    proj.upsert_part("hole", code='result = mesh_boolean("ref", Cylinder(3, 20), "subtract")')
    info = proj.build("hole")["info"]
    assert info["ok"], info
    assert info["size"] == [10.0, 10.0, 10.0]
    assert info["watertight"] is True
    assert abs(info["volume_mm3"] - (1000 - math.pi * 9 * 10)) < 5  # cylinder is tessellated, not exact


def test_mesh_boolean_result_is_skipped_in_step_export(proj, tmp_path):
    f = tmp_path / "cube.stl"
    trimesh.creation.box((10, 10, 10)).export(f)
    proj.import_mesh("ref", f)
    proj.upsert_part("hole", code='result = mesh_boolean("ref", Cylinder(3, 20), "subtract")')
    proj.build("hole")
    assert proj.find("hole")  # sanity: part exists
    assert proj.build("hole")["shape"] is None  # no BRep shape - consistent with plain imported meshes


def test_mesh_boolean_bad_op_is_reported(proj, tmp_path):
    f = tmp_path / "cube.stl"
    trimesh.creation.box((10, 10, 10)).export(f)
    proj.import_mesh("ref", f)
    proj.upsert_part("hole", code='result = mesh_boolean("ref", Cylinder(3, 20), "xor")')
    info = proj.build("hole")["info"]
    assert info["ok"] is False
    assert "op must be" in info["error"]


def test_mesh_import_scale_is_applied(proj, tmp_path):
    f = tmp_path / "cube.stl"
    trimesh.creation.box((10, 10, 10)).export(f)
    proj.import_mesh("ref", f)
    proj.upsert_part("ref", scale=[2, 1, 1])
    info = proj.build("ref")["info"]
    assert info["ok"] and info["size"] == [20.0, 10.0, 10.0]
    assert abs(info["volume_mm3"] - 2000) < 1e-6


def test_project_is_persisted_and_reloaded(proj):
    proj.upsert_part("a", code=BOX, color="#123456")
    P._open.clear()
    again = P.get_project(proj.name)
    assert again.find("a")["color"] == "#123456"
    assert again.rev >= 1


def test_import_3mf_and_obj(proj, tmp_path):
    """3MF import needs trimesh's optional deps (networkx, lxml) – make sure they are installed."""
    from cadstudio.export3mf import export_3mf

    proj.upsert_part("a", code=BOX)
    path = export_3mf(proj)["path"]
    proj.import_mesh("from3mf", path)
    obj = tmp_path / "cube.obj"
    trimesh.creation.box((4, 4, 4)).export(obj)
    proj.import_mesh("fromobj", obj)
    assert proj.build("from3mf")["info"]["size"] == [20.0, 10.0, 5.0]
    assert proj.build("fromobj")["info"]["size"] == [4.0, 4.0, 4.0]
