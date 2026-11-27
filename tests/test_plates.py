# SPDX-License-Identifier: GPL-3.0-or-later
"""Build plates: plate field, plate grid, arrange_plates, multi-plate / split 3MF export, preview."""
import xml.etree.ElementTree as ET
import zipfile

import trimesh
from fastapi.testclient import TestClient

from cadstudio import project as P
from cadstudio.export3mf import export_3mf
from cadstudio.render import render_png

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
DISC = "result = Cylinder(100, 3, align=(Align.CENTER, Align.CENTER, Align.MIN))"  # 200 mm: one per plate
SMALL = "result = Box(40, 30, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))"


def test_plate_grid_matches_slicer_layout():
    assert P.plate_columns(1) == 1
    assert P.plate_columns(2) == 2
    assert P.plate_columns(4) == 2
    assert P.plate_columns(5) == 3
    stride = P.BED[0] * (1 + P.PLATE_GAP)
    assert P.plate_origin(1, 2) == (0, 0)
    assert P.plate_origin(2, 2) == (stride, 0)
    assert P.plate_origin(3, 4) == (0, -stride)


def test_plate_field_and_count(proj):
    proj.upsert_part("a", code=DISC)
    assert proj.find("a")["plate"] == 1 and proj.plate_count == 1
    proj.upsert_part("b", code=DISC, plate=3)
    assert proj.plate_count == 3
    s = proj.summary()
    assert s["plates"] == 3 and set(s["plate_origins"]) == {"1", "2", "3"}
    # changing the plate must not rebuild the part (plate is not part of the geometry)
    key = proj.build("b")["key"]
    proj.upsert_part("b", plate=2)
    assert proj.build("b")["key"] == key


def test_add_remove_plate(proj):
    proj.upsert_part("a", code=SMALL)
    proj.upsert_part("b", code=SMALL, plate=2)
    proj.upsert_part("c", code=SMALL, plate=3)
    assert proj.add_plate() == 4
    proj.remove_plate(2)
    assert proj.plate_count == 3
    assert proj.part_plate("b") == 1 and proj.part_plate("c") == 2


def test_arrange_spreads_over_plates(proj):
    proj.upsert_part("side_a", code=DISC)
    proj.upsert_part("side_b", code=DISC)
    res = proj.arrange_plates()
    assert res["plates"] == 2
    assert {proj.part_plate("side_a"), proj.part_plate("side_b")} == {1, 2}
    for n in ("side_a", "side_b"):
        info = proj.build(n)["info"]
        assert -125 <= info["bbox_min"][0] and info["bbox_max"][0] <= 125
        assert -125 <= info["bbox_min"][1] and info["bbox_max"][1] <= 125


def test_arrange_keeps_assemblies_together(proj):
    proj.upsert_part("lid", code=SMALL)
    proj.upsert_part("text", code="result = Pos(0, 0, 5) * Box(20, 8, 1, align=(Align.CENTER, Align.CENTER, Align.MIN))")
    proj.upsert_part("big", code=DISC, location=[0, 0, 0, 0, 0, 0])
    proj.arrange_plates()
    lid, text = proj.build("lid")["info"], proj.build("text")["info"]
    # text still centred on the lid and on the same plate
    assert abs((lid["bbox_min"][0] + lid["bbox_max"][0]) - (text["bbox_min"][0] + text["bbox_max"][0])) < 1e-6
    assert proj.part_plate("lid") == proj.part_plate("text")


def test_arrange_packs_small_parts_on_one_plate(proj):
    for i in range(4):
        proj.upsert_part(f"p{i}", code=SMALL)  # left on top of each other at the origin -> separate prints
    proj.upsert_part("q", code=SMALL, location=[200, 0, 0, 0, 0, 0])  # off the bed
    res = proj.arrange_plates()
    assert res["plates"] == 1
    assert proj.part_plate("q") == 1
    info = proj.build("q")["info"]
    assert info["bbox_max"][0] <= 125


def test_arrange_keeps_referenced_groups_in_place(proj):
    proj.upsert_part("base", code="result = Box(30, 30, 3) - part('logo')", color="#FFFFFF")
    proj.upsert_part("logo", code="result = Pos(0, 0, 1.5) * Cylinder(5, 1.5, align=(Align.CENTER, Align.CENTER, Align.MIN))",
                     color="#D62828")
    proj.upsert_part("other", code=DISC)
    proj.arrange_plates()
    assert proj.find("base")["location"][:2] == [0, 0] and proj.find("logo")["location"][:2] == [0, 0]
    assert proj.part_plate("base") == proj.part_plate("logo") != proj.part_plate("other")


def test_multi_plate_3mf(proj, monkeypatch, tmp_path):
    monkeypatch.setenv("CADSTUDIO_ORCA_PROFILES", str(tmp_path / "no-profiles"))
    proj.upsert_part("side_a", code=DISC, filament=1, color="#1D3557")
    proj.upsert_part("side_b", code=DISC, filament=1, color="#1D3557", plate=2)
    res = export_3mf(proj, mode="objects")
    assert res["plates"] == {"1": ["side_a"], "2": ["side_b"]}
    # without slicer profiles there is no project config, so Orca / Anycubic would import it on one plate
    assert any("beside the build plate" in w for w in res["warnings"]) and "project_settings" not in res
    with zipfile.ZipFile(res["path"]) as z:
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    plates = cfg.findall("plate")
    assert [p.find("metadata[@key='plater_id']").get("value") for p in plates] == ["1", "2"]
    assert all(len(p.findall("model_instance")) == 1 for p in plates)
    scene = trimesh.load(res["path"])
    xs = sorted(g.bounds[:, 0].mean() for g in scene.dump())
    stride = P.BED[0] * (1 + P.PLATE_GAP)
    assert abs(xs[0] - P.BED[0] / 2) < 0.5 and abs(xs[1] - (P.BED[0] / 2 + stride)) < 0.5


def test_single_plate_and_split_export(proj):
    proj.upsert_part("side_a", code=DISC)
    proj.upsert_part("side_b", code=DISC, plate=2)
    one = export_3mf(proj, plate=2)
    assert one["parts"] == ["side_b"]
    assert not any("beside the build plate" in w for w in one["warnings"])
    scene = trimesh.load(one["path"])  # a single plate sits on the bed, centred
    lo, hi = scene.bounds
    assert lo[0] >= 0 and lo[1] >= 0 and hi[0] <= P.BED[0] and hi[1] <= P.BED[1]
    split = export_3mf(proj, split_plates=True)
    assert len(split["paths"]) == 2 and all(p.endswith((".3mf",)) for p in split["paths"])
    assert "plate1" in split["paths"][0] and "plate2" in split["paths"][1]
    for path in split["paths"]:  # every per-plate file is on the bed
        lo, hi = trimesh.load(path).bounds
        assert lo[0] >= 0 and lo[1] >= 0 and hi[0] <= P.BED[0] and hi[1] <= P.BED[1]
    assert not any("beside the build plate" in w for w in split["warnings"])


def test_render_lays_plates_out(proj):
    proj.upsert_part("side_a", code=DISC)
    proj.upsert_part("side_b", code=DISC, plate=2)
    png, errors = render_png(proj, view="top", size=300)
    assert png[:4] == b"\x89PNG" and not errors
    png2, _ = render_png(proj, view="top", size=300, plate=2)
    assert png2[:4] == b"\x89PNG"


def test_plate_api_and_no_cache(proj):
    from cadstudio.web import app
    c = TestClient(app)
    proj.upsert_part("side_a", code=DISC)
    proj.upsert_part("side_b", code=DISC)
    r = c.put("/api/parts/side_b", json={"plate": 2, "scale": [1, 1, 1]})
    assert r.status_code == 200 and r.json()["plates"] == 2
    assert r.headers["cache-control"] == "no-store"
    assert c.post("/api/plates").json()["plates"] == 3
    assert c.delete("/api/plates/3").json()["plates"] == 2
    r = c.post("/api/plates/arrange", json={})
    assert r.json()["arrange"]["plates"] == 2
    assert c.get("/").headers["cache-control"] == "no-store"
    assert c.get("/static/app.js").headers["cache-control"] == "no-cache"


def test_auto_plate_name():
    assert P.auto_plate_name(["wiel_1", "wiel_2", "as_1", "deck"]) == "wiel x2, as, deck"
    assert P.auto_plate_name(["koppelarm_V1", "koppelarm_V2", "koppelarm_A1"]) == "koppelarm_V x2, koppelarm_A"
    assert P.auto_plate_name([]) == ""
    assert P.auto_plate_name(["onderstel_v3", "as_1"]) == "onderstel_v3, as_1"
    long = P.auto_plate_name([f"part{c}" for c in "abcdefghijklmnop"], limit=20)
    assert len(long) <= 25 and long.endswith(tuple("0123456789"))


def test_plate_names_in_3mf(proj):
    proj.upsert_part("wiel_1", code=SMALL)
    proj.upsert_part("wiel_2", code=SMALL, location=[60, 0, 0])
    proj.upsert_part("deck", code=DISC, plate=2)
    proj.upsert_part("arm", code=SMALL, plate=3)
    names = proj.set_plate_name(2, "  loc-dek  ")
    assert names == {"1": "wiel x2", "2": "loc-dek", "3": "arm"}
    assert proj.summary()["plate_names"]["2"] == "loc-dek"

    def plate_names(path):
        with zipfile.ZipFile(path) as z:
            cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
        return [p.find("metadata[@key='plater_name']").get("value") for p in cfg.findall("plate")]

    assert plate_names(export_3mf(proj, mode="objects")["path"]) == ["wiel x2", "loc-dek", "arm"]
    assert plate_names(export_3mf(proj, plate=2)["path"]) == ["loc-dek"]
    split = export_3mf(proj, split_plates=True)
    assert [plate_names(p) for p in split["paths"]] == [["wiel x2"], ["loc-dek"], ["arm"]]
    # empty name = automatic again; removing a plate shifts the names of later plates
    proj.set_plate_name(3, "armen")
    proj.set_plate_name(2, "")
    assert proj.plate_name(2) == "deck"
    proj.remove_plate(2)
    assert proj.plate_names == {"2": "armen"}


def test_plate_name_api(proj):
    from cadstudio.web import app
    c = TestClient(app)
    proj.upsert_part("side_a", code=DISC)
    proj.upsert_part("side_b", code=DISC, plate=2)
    r = c.put("/api/plates/2/name", json={"name": "tweede"})
    assert r.status_code == 200 and r.json()["plate_names"] == {"1": "side_a", "2": "tweede"}
    assert c.put("/api/plates/5/name", json={"name": "x"}).status_code >= 400
