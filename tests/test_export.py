# SPDX-License-Identifier: GPL-3.0-or-later
import xml.etree.ElementTree as ET
import zipfile

import trimesh

from cadstudio.export3mf import export_3mf, export_step, export_stl

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}


def _two_colour(proj):
    proj.upsert_part("base", code="result = Box(30, 30, 3) - part('logo')", color="#FFFFFF", filament=1)
    proj.upsert_part("logo", code="result = Pos(0, 0, 1.5) * Cylinder(5, 1.5, align=(Align.CENTER, Align.CENTER, Align.MIN))",
                     color="#D62828", filament=2)


def test_orca_3mf_has_extruder_per_part(proj):
    _two_colour(proj)
    res = export_3mf(proj)
    assert res["filament_slots"] == {"1": ["base (#FFFFFF)"], "2": ["logo (#D62828)"]}
    with zipfile.ZipFile(res["path"]) as z:
        model = ET.fromstring(z.read("3D/3dmodel.model"))
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    objs = model.findall(".//m:object", NS)
    assert len([o for o in objs if o.find("m:components", NS) is not None]) == 1
    parts = {p.find("metadata[@key='name']").get("value"): p.find("metadata[@key='extruder']").get("value")
             for p in cfg.iter("part")}
    assert parts == {"base": "1", "logo": "2"}
    # geometry sits on the bed
    scene = trimesh.load(res["path"])
    assert abs(scene.bounds[0][2]) < 1e-6


def test_filament_weight_and_cost_estimate(proj):
    proj.upsert_part("a", code="result = Box(10, 10, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))",
                      color="#FFFFFF", filament=1)  # 1000 mm^3 = 1 cm^3
    res = export_3mf(proj, filament_density_g_cm3=1.24, filament_price_eur_kg=20)
    assert abs(res["total_g_solid_estimate"] - 1.24) < 0.05
    assert res["filament_g_solid_estimate"] == {"1": res["total_g_solid_estimate"]}
    assert abs(res["cost_eur_solid_estimate"] - 1.24 / 1000 * 20) < 0.01  # cost is rounded to cents


def test_filament_weight_without_price_omits_cost(proj):
    proj.upsert_part("a", code="result = Box(10, 10, 10)")
    res = export_3mf(proj)
    assert "cost_eur_solid_estimate" not in res
    assert res["total_g_solid_estimate"] > 0


def test_print_time_estimate_scales_with_rate(proj):
    proj.upsert_part("a", code="result = Box(10, 10, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))")
    res = export_3mf(proj, print_rate_cm3_per_hour=10.0)  # 1 cm^3 at 10 cm^3/h -> 0.1 h
    assert abs(res["print_time_hours_estimate"] - 0.1) < 1e-6
    res2 = export_3mf(proj, print_rate_cm3_per_hour=None)
    assert "print_time_hours_estimate" not in res2


def test_prusa_3mf_volumes(proj):
    _two_colour(proj)
    res = export_3mf(proj, flavor="prusa")
    with zipfile.ZipFile(res["path"]) as z:
        cfg = ET.fromstring(z.read("Metadata/Slic3r_PE_model.config"))
    vols = cfg.findall(".//volume")
    assert [v.find("metadata[@key='extruder']").get("value") for v in vols] == ["1", "2"]
    assert int(vols[1].get("firstid")) == int(vols[0].get("lastid")) + 1


def test_objects_mode_and_slot_warnings(proj):
    for i in range(5):
        proj.upsert_part(f"p{i}", code=f"result = Pos({i * 15}, 0, 0) * Box(10, 10, 2)", color=f"#00000{i}", filament=i + 1)
    res = export_3mf(proj, mode="objects")
    assert any("second" in w for w in res["warnings"])
    with zipfile.ZipFile(res["path"]) as z:
        model = ET.fromstring(z.read("3D/3dmodel.model"))
    assert len(model.findall(".//m:build/m:item", NS)) == 5


def test_stl_and_step(proj):
    _two_colour(proj)
    stl = export_stl(proj)
    assert len(stl["files"]) == 2
    assert all(trimesh.load(f).is_watertight for f in stl["files"])
    step = export_step(proj)
    assert open(step["path"]).read(13) == "ISO-10303-21;"
