# SPDX-License-Identifier: GPL-3.0-or-later
import xml.etree.ElementTree as ET
import zipfile

import pytest

from cadstudio.export3mf import export_3mf, pause_layer_top

PAUSED = """result = Box(20, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
pause_at = [7.2]
"""


@pytest.mark.parametrize("at, lh, top", [(7.2, 0.2, 7.4), (7.25, 0.2, 7.4), (7.39, 0.2, 7.4), (7.2, 0.28, 7.48), (7.0, 0.28, 7.2),
                                          (7.2, 0.12, 7.28), (0.1, 0.2, 0.2), (4.2, 0.2, 4.4)])
def test_pause_is_before_the_first_layer_above(at, lh, top):
    assert pause_layer_top(at, lh) == pytest.approx(top)


def _read(path, name):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(name)) if name in z.namelist() else None


def test_orca_3mf_has_pauses_per_plate(proj, tmp_path):
    proj.upsert_part("a", code=PAUSED, plate=1)
    proj.upsert_part("b", code="result = Box(10, 10, 5)", plate=2)
    proj.upsert_part("c", code=PAUSED.replace("7.2", "3.0"), plate=3)
    res = export_3mf(proj, tmp_path / "all.3mf")
    root = _read(res["path"], "Metadata/custom_gcode_per_layer.xml")
    assert root.tag == "custom_gcodes_per_layer"
    plates = {p.find("plate_info").get("id"): [lay.attrib for lay in p.findall("layer")] for p in root.findall("plate")}
    assert set(plates) == {"1", "3"}
    assert plates["1"][0]["top_z"] == "7.4" and plates["1"][0]["type"] == "1" and plates["1"][0]["gcode"] == "M601"
    assert plates["3"][0]["top_z"] == "3.2"
    assert res["pauses"] == {"1": [{"at_mm": 7.2, "layer_top_mm": 7.4}], "3": [{"at_mm": 3.0, "layer_top_mm": 3.2}]}
    assert any("Open as project" in w for w in res["warnings"])


def test_single_plate_and_split_files_use_plate_1(proj, tmp_path):
    proj.upsert_part("a", code=PAUSED, plate=2)
    res = export_3mf(proj, tmp_path / "p2.3mf", plate=2)
    root = _read(res["path"], "Metadata/custom_gcode_per_layer.xml")
    assert [p.find("plate_info").get("id") for p in root.findall("plate")] == ["1"]
    split = export_3mf(proj, tmp_path / "split.3mf", split_plates=True)
    assert _read(split["paths"][0], "Metadata/custom_gcode_per_layer.xml") is not None


def test_layer_height_and_prusa_flavour(proj, tmp_path):
    proj.upsert_part("a", code=PAUSED)
    res = export_3mf(proj, tmp_path / "fine.3mf", print_settings={"layer_height_mm": 0.12})
    lay = _read(res["path"], "Metadata/custom_gcode_per_layer.xml").find("plate/layer")
    assert lay.get("top_z") == "7.28"
    res = export_3mf(proj, tmp_path / "prusa.3mf", flavor="prusa")
    root = _read(res["path"], "Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml")
    assert root.tag == "custom_gcodes_per_print_z" and root.find("code").get("print_z") == "7.4"
    assert root.find("mode").get("value") == "SingleExtruder"


def test_pauses_can_be_left_out(proj, tmp_path):
    proj.upsert_part("a", code=PAUSED)
    res = export_3mf(proj, tmp_path / "none.3mf", pauses=False)
    assert _read(res["path"], "Metadata/custom_gcode_per_layer.xml") is None and "pauses" not in res
    res = export_3mf(proj, tmp_path / "plain.3mf")
    assert res["pauses"]
    proj.upsert_part("a", code="result = Box(5, 5, 5)")
    assert "pauses" not in export_3mf(proj, tmp_path / "nopause.3mf")
