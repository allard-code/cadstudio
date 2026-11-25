# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cadstudio import printing, slicer
from cadstudio.fitcheck import check_fit
from cadstudio.project import PartError
from cadstudio.render import render_assembly_png

DECK = """deck = Box(40, 20, 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
assembled = Pos(0, 0, 20) * deck                 # sits 20 mm up in the model
result = deck                                    # printed flat on the bed
"""

WHEELS = """w = Cylinder(5, 3)
assembled = {"left": Pos(-15, 0, 5) * Rot(0, 90, 0) * w, "right": Pos(15, 0, 5) * Rot(0, 90, 0) * w}
result = Pos(-8, 0, 1.5) * w + Pos(8, 0, 1.5) * w
"""


def test_parts_define_their_own_assembly_items(proj):
    proj.upsert_part("deck", code=DECK, color="#1F4E8C")
    proj.upsert_part("wheels", code=WHEELS)
    proj.upsert_assembly_item("rail", code="result = Box(60, 20, 2, align=(Align.CENTER, Align.CENTER, Align.MAX))")
    specs = {a["name"]: a for a in proj.assembly_specs()}
    assert list(specs) == ["deck", "wheels/left", "wheels/right", "rail"]
    assert specs["deck"]["source"] == "deck" and specs["deck"]["color"] == "#1F4E8C"
    info = proj.build_assembly_item("deck")["info"]
    assert info["ok"] and info["bbox_min"][2] == pytest.approx(20)
    assert proj.build("deck")["info"]["bbox_min"][2] == pytest.approx(0)       # the print stays flat
    assert [a["name"] for a in proj.summary()["assembly"]] == list(specs)
    png, errors = render_assembly_png(proj, view="iso", size=400)
    assert png[:4] == b"\x89PNG" and not errors
    from cadstudio.web import app
    c = TestClient(app)
    assert c.get("/api/assembly/mesh/wheels%2Fleft").status_code == 200
    assert c.put("/api/assembly/wheels%2Fleft", json={"ghost": True}).status_code == 200
    assert proj.find_assembly_item("wheels/left")["ghost"] is True


def test_overrides_and_protection_for_part_items(proj):
    proj.upsert_part("deck", code=DECK)
    proj.upsert_assembly_item("deck", ghost=True, color="#ff0000")
    spec = proj.find_assembly_item("deck")
    assert spec["ghost"] and spec["color"] == "#ff0000" and spec["source"] == "deck"
    with pytest.raises(PartError, match="comes from part"):
        proj.upsert_assembly_item("deck", code="result = Box(1, 1, 1)")
    proj.delete_assembly_item("deck")              # removes the override only
    assert proj.find_assembly_item("deck")["ghost"] is False
    with pytest.raises(PartError, match="assembled"):
        proj.delete_assembly_item("deck")


def test_fit_check_sees_part_items(proj):
    proj.upsert_part("deck", code=DECK)
    proj.upsert_assembly_item("block", code="result = Pos(0, 0, 18) * Box(4, 4, 4.1, align=(Align.CENTER,) * 2 + (Align.MIN,))")
    r = check_fit(proj)
    assert r["issues"][0]["status"] == "overlap"


def test_bad_assembled_value_is_a_build_error(proj):
    proj.upsert_part("x", code="assembled = 5\nresult = Box(1, 1, 1)")
    info = proj.build("x")["info"]
    assert info["ok"] is False and "assembled" in info["error"]


# ---------------------------------------------------------------- pauses

GCODE = "".join(f";LAYER_CHANGE\n;Z:{z:.1f}\n;HEIGHT:0.2\nG1 Z{z:.1f}\nG1 X1 Y1 E1\n" for z in
                [0.2 * k for k in range(1, 26)])


def test_pause_at_collects_plate_heights(proj):
    proj.upsert_part("cap", code="result = Box(10, 10, 5)\npause_at = [3.2, 1.0]", location=[0, 0, 2, 0, 0, 0])
    assert proj.build("cap")["info"]["pause_at"] == [3.0, 5.2]
    assert printing.plate_pauses(proj, 1) == [3.0, 5.2]
    proj.upsert_part("tilted", code="result = Box(2, 2, 2)\npause_at = 1", location=[0, 0, 0, 90, 0, 0])
    assert proj.build("tilted")["info"]["ok"] is False


def test_insert_pauses_before_the_covering_layer(tmp_path):
    g = Path(tmp_path / "a.gcode")
    g.write_text(GCODE)
    done = printing.insert_pauses(g, [3.0, 3.1, 4.4, 99], "M601")
    assert [d["layer_z_mm"] for d in done] == [pytest.approx(3.2), pytest.approx(4.6)]
    text = g.read_text()
    assert text.count("\nM601\n") == 2
    # the pause comes right after the layer marker of Z 3.2, before that layer prints
    i = text.index(";Z:3.2")
    assert text.index("M601", i) < text.index("G1 Z3.2", i)


def test_slice_plate_adds_pauses(proj, monkeypatch, tmp_path):
    proj.upsert_part("cap", code="result = Box(10, 10, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))\npause_at = 3")

    def fake_slice(model, out_dir, **kw):
        dest = Path(out_dir) / f"{Path(model).stem}.gcode"
        dest.write_text(GCODE + "; estimated printing time (normal mode) = 12m 3s\n; total filament used [g] = 1.50\n")
        return {"gcode": str(dest), "stats": {}, "log": ""}

    monkeypatch.setattr(slicer, "available", lambda: True)
    monkeypatch.setattr(slicer, "slice_3mf", fake_slice)
    monkeypatch.setattr(slicer, "flatten", lambda kind, name, vendor=None: {"machine_pause_gcode": "PAUSE"})
    res = printing.slice_plate(proj, plate=1, pauses=[4.0])
    assert res["ok"] and [p["layer_z_mm"] for p in res["pauses"]] == [pytest.approx(3.2), pytest.approx(4.2)]
    assert Path(res["gcode"]).read_text().count("\nPAUSE\n") == 2
    last = printing.last_slice(proj, 1)
    assert last["pauses"] == 2 and last["outdated"] is False

    from cadstudio.web import app
    c = TestClient(app)
    st = c.get("/api/printing", params={"plate": 1}).json()
    assert st["slicer"] is True and st["last"]["pauses"] == 2 and st["pauses"] == [3.0]
    r = c.post("/api/slice", json={"plate": 1})
    assert r.status_code == 200 and r.json()["last"]["pauses"] == 1
    assert c.post("/api/print", json={"plate": 1}).status_code == 422   # Home Assistant not configured
