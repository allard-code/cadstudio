# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
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
