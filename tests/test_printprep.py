# SPDX-License-Identifier: GPL-3.0-or-later
"""Print preparation: orientation suggestions and print settings in the 3MF / slicer."""
import math
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pytest

from cadstudio import orient as O
from cadstudio import printsettings as PS
from cadstudio.export3mf import export_3mf
from cadstudio.printcheck import find_floating
from cadstudio.project import rot_matrix

MUSHROOM = ("result = Box(6, 6, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)) + "
            "Pos(0, 0, 10) * Box(30, 10, 2, align=(Align.CENTER, Align.CENTER, Align.MIN))")


# --------------------------------------------------------------------------- orientation maths

@pytest.mark.parametrize("angles", [(0, 0, 0), (90, 0, 0), (30, -40, 120), (-170, 10, 45), (0, 90, 30), (0, -90, 0)])
def test_euler_roundtrip(angles):
    R = rot_matrix(*angles)
    back = O.euler_from_matrix(R)
    assert np.allclose(rot_matrix(*back), R, atol=1e-6)


@pytest.mark.parametrize("d", [[0, 0, -1], [0, 0, 1], [1, 0, 0], [0.3, -0.5, 0.8], [-1, 2, -0.1]])
def test_rotation_to_down(d):
    R = O.rotation_to_down(np.array(d, float))
    v = R @ (np.array(d, float) / np.linalg.norm(d))
    assert np.allclose(v, [0, 0, -1], atol=1e-9)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)


def _mesh(code_shape):
    from cadstudio.project import tessellate
    return tessellate(code_shape)


def test_standing_plate_is_laid_flat():
    import build123d as bd
    V, F = _mesh(bd.Box(40, 2, 30, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)))
    best = O.suggest(V, F)["candidates"][0]
    assert best["height_mm"] == pytest.approx(2, abs=0.01)
    assert best["support_area_mm2"] == 0


def test_mushroom_is_flipped_onto_its_cap():
    import build123d as bd
    V, F = _mesh(bd.Box(6, 6, 10, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
                 + bd.Pos(0, 0, 10) * bd.Box(30, 10, 2, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)))
    res = O.suggest(V, F)
    assert res["current"]["support_area_mm2"] > 200          # the underside of the cap overhangs
    best = res["candidates"][0]
    assert best["support_area_mm2"] == 0
    assert best["bed_contact_mm2"] == pytest.approx(300, rel=0.02)


def test_load_direction_keeps_the_load_along_the_layers():
    import build123d as bd
    # a 60 mm bar along X; standing up would be smaller footprint, but a pull along X then splits the layers
    V, F = _mesh(bd.Box(60, 8, 8, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)))
    best = O.suggest(V, F, load="x")["candidates"][0]
    assert best["load_across_layers"] == 0
    standing = O.evaluate(V, F, rot_matrix(0, 90, 0), load=np.array([1.0, 0, 0]))
    assert standing["load_across_layers"] == 1
    with pytest.raises(ValueError):
        O.parse_load("w")


# --------------------------------------------------------------------------- MCP tool: apply

def test_suggest_orientation_applies_to_the_whole_group(proj):
    from cadstudio.mcp_server import suggest_orientation
    proj.upsert_part("body", type="code", code=MUSHROOM)
    # an inlay set flush into the top of the cap: it must turn with the body
    proj.upsert_part("inlay", type="code",
                     code="result = Pos(8, 0, 11.4) * Box(6, 4, 0.6, align=(Align.CENTER, Align.CENTER, Align.MIN))",
                     color="#D62828")

    def centres():
        return {n: proj.build(n)["mesh"][0].mean(axis=0) for n in ("body", "inlay")}

    before = centres()
    res = suggest_orientation(plate=1)
    assert res["ok"] and res["parts"] == ["body", "inlay"]
    assert res["candidates"][0]["support_area_mm2"] < res["current"]["support_area_mm2"]
    res = suggest_orientation(plate=1, apply=1)
    assert res["applied"]["rank"] == 1
    after = centres()
    # rigid: the distance between the parts is unchanged
    d0 = np.linalg.norm(before["body"] - before["inlay"])
    d1 = np.linalg.norm(after["body"] - after["inlay"])
    assert d1 == pytest.approx(d0, abs=1e-3)
    # back on the bed, nothing floating, and the cap is now the base
    allv = np.vstack([proj.build(n)["mesh"][0] for n in ("body", "inlay")])
    assert allv[:, 2].min() == pytest.approx(0, abs=1e-6)
    items = [(n, *proj.build(n)["mesh"]) for n in ("body", "inlay")]
    assert find_floating(items) == []
    assert suggest_orientation(plate=1)["current"]["support_area_mm2"] == 0


def test_suggest_orientation_errors(proj):
    from cadstudio.mcp_server import suggest_orientation
    assert suggest_orientation(plate=1)["ok"] is False
    proj.upsert_part("body", type="code", code=MUSHROOM)
    assert suggest_orientation(load_direction="q")["ok"] is False
    assert suggest_orientation(apply=99)["ok"] is False


# --------------------------------------------------------------------------- print settings

def test_normalize_and_profiles():
    assert PS.normalize({"infill_percent": "25", "infill_pattern": "Gyroid", "supports": "yes",
                         "wall_loops": None}) == {"infill_percent": 25.0, "infill_pattern": "gyroid",
                                                  "supports": True}
    with pytest.raises(PS.PrintSettingsError, match="Unknown infill_pattern"):
        PS.normalize({"infill_pattern": "spaghetti"})
    with pytest.raises(PS.PrintSettingsError, match="between"):
        PS.normalize({"infill_percent": 140})
    with pytest.raises(PS.PrintSettingsError, match="whole object"):
        PS.normalize({"layer_height_mm": 0.2}, part_level=True)
    with pytest.raises(PS.PrintSettingsError, match="Unknown profile"):
        PS.profile_settings("bulletproof")
    assert "layer_height_mm" not in PS.profile_settings("draft", part_level=True)
    orca = PS.to_orca({"infill_percent": 30.0, "supports": True, "support_type": "tree", "layer_height_mm": 0.12})
    assert orca == {"sparse_infill_density": "30%", "enable_support": "1", "support_type": "tree(auto)",
                    "layer_height": "0.12"}
    prusa, warn = PS.to_prusa({"wall_loops": 4, "infill_pattern": "tri-hexagon"})
    assert prusa == {"perimeters": "4"} and warn


def _cfg(path):
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.startswith("Metadata/") and n.endswith(".config"))
        return ET.fromstring(z.read(name))


def _meta(el):
    return {m.get("key"): m.get("value") for m in el.findall("metadata")}


def test_settings_are_written_into_the_orca_3mf(proj, tmp_path):
    from cadstudio.mcp_server import set_print_settings
    proj.upsert_part("body", type="code", code=MUSHROOM)
    proj.upsert_part("inlay", type="code",
                     code="result = Pos(8, 0, 11.4) * Box(6, 4, 0.6, align=(Align.CENTER, Align.CENTER, Align.MIN))")
    r = set_print_settings(profile="functional", infill_percent=20, supports=True)
    assert r["ok"] and r["project"]["effective"]["wall_loops"] == 4
    assert r["project"]["effective"]["infill_percent"] == 20
    assert set_print_settings(part="inlay", profile="decorative")["ok"]
    bad = set_print_settings(part="inlay", layer_height_mm=0.1)
    assert bad["ok"] is False and "whole object" in bad["error"]
    assert set_print_settings(part="nope", wall_loops=3)["ok"] is False

    res = export_3mf(proj, tmp_path / "a.3mf")
    assert res["print_settings"]["object"]["wall_loops"] == 4
    cfg = _cfg(res["path"])
    obj = cfg.find("object")
    om = _meta(obj)
    assert om["wall_loops"] == "4" and om["sparse_infill_density"] == "20%" and om["enable_support"] == "1"
    parts = {(_meta(p)["name"]): _meta(p) for p in obj.findall("part")}
    assert parts["inlay"]["wall_loops"] == "2" and parts["inlay"]["sparse_infill_density"] == "10%"
    assert "wall_loops" not in parts["body"]

    pr = export_3mf(proj, tmp_path / "p.3mf", flavor="prusa")
    pobj = _cfg(pr["path"]).find("object")
    assert {m.get("key"): m.get("value") for m in pobj.findall("metadata")}["perimeters"] == "4"
    vols = pobj.findall("volume")
    assert any({m.get("key"): m.get("value") for m in v.findall("metadata")}.get("perimeters") == "2" for v in vols)

    # clear resets the project level; parts keep theirs
    r = set_print_settings(clear=True)
    assert r["project"]["stored"] == {} and "inlay" in r["parts"]
    assert "print_settings" in export_3mf(proj, tmp_path / "b.3mf")
    set_print_settings(part="inlay", clear=True)
    assert "print_settings" not in export_3mf(proj, tmp_path / "c.3mf")


def test_slice_plate_uses_project_settings(proj, monkeypatch):
    from cadstudio import mcp_server, slicer
    proj.upsert_part("body", type="code", code=MUSHROOM)
    mcp_server.set_print_settings(profile="strong", layer_height_mm=0.16)
    seen = {}

    def fake_slice(model, out_dir, printer=None, process=None, filaments=None, overrides=None, vendor=None,
                   timeout=900, settings=None):
        seen["settings"] = settings
        seen["cfg"] = _meta(_cfg(model).find("object"))
        g = out_dir / f"{model.stem}.gcode"
        g.write_text("; done\n")
        return {"gcode": str(g), "stats": {}, "printer": printer, "process": process, "filaments": filaments}

    monkeypatch.setattr(slicer, "available", lambda: True)
    monkeypatch.setattr(slicer, "slice_3mf", fake_slice)
    res = mcp_server.slice_plate(plate=1, infill_percent=15)
    assert res["ok"], res
    assert seen["settings"]["wall_loops"] == "6" and seen["settings"]["layer_height"] == "0.16"
    assert seen["settings"]["sparse_infill_density"] == "15%"      # the per-slice override wins
    assert seen["cfg"]["sparse_infill_density"] == "15%"            # ... also in the 3MF object settings
    assert res["print_settings"]["object"]["infill_percent"] == 15
    assert mcp_server.slice_plate(plate=1, infill_pattern="nope")["ok"] is False


def test_slicer_applies_preformatted_settings(tmp_path, monkeypatch):
    """slice_3mf: settings (orca keys) land in the process JSON, overrides on top."""
    import json

    from cadstudio import slicer
    captured = {}

    def fake_run(cmd, cwd=None, env=None, capture_output=None, text=None, timeout=None):
        files = cmd[cmd.index("--load-settings") + 1].split(";")
        captured["proc"] = json.loads(open(files[1]).read())
        raise slicer.SlicerError("stop")

    monkeypatch.setattr(slicer, "orca_binary", lambda: tmp_path / "orca")
    monkeypatch.setattr(slicer, "flatten", lambda kind, name, vendor=None, root=None: {"name": name})
    monkeypatch.setattr(slicer, "filament_preset", lambda m, p=None, v=None: m)
    monkeypatch.setattr(slicer.subprocess, "run", fake_run)
    with pytest.raises(slicer.SlicerError):
        slicer.slice_3mf(tmp_path / "x.3mf", tmp_path / "out", process="P",
                         settings={"wall_loops": "6", "sparse_infill_density": "50%"},
                         overrides={"infill_percent": 20})
    assert captured["proc"]["wall_loops"] == "6"
    assert captured["proc"]["sparse_infill_density"] == "20%"


def test_euler_handles_rounding():
    assert O.euler_from_matrix(rot_matrix(180, 0, 0)) in ([180.0, 0.0, 0.0], [-180.0, 0.0, 0.0])
    assert all(not math.isnan(a) for a in O.euler_from_matrix(np.eye(3)))
