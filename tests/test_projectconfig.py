# SPDX-License-Identifier: GPL-3.0-or-later
"""Multi-plate 3MF as a slicer project: Metadata/project_settings.config from the printer profiles."""
import json
import zipfile

import pytest

from cadstudio import projectconfig
from cadstudio.export3mf import export_3mf

PRINTER = "Anycubic Kobra S1 0.4 nozzle"
DISC = "result = Cylinder(20, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))"


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    """A tiny OrcaSlicer profile tree with the same shape as resources/profiles."""
    root = tmp_path / "profiles"
    v = root / "Anycubic"
    for kind in ("machine", "process", "filament"):
        (v / kind).mkdir(parents=True)

    def put(kind, name, data):
        (v / kind / f"{name}.json").write_text(json.dumps({"name": name, **data}))

    put("machine", "fdm_machine_common", {"type": "machine", "instantiation": "false",
                                           "nozzle_diameter": ["0.4"], "printable_height": "250"})
    put("machine", PRINTER, {"type": "machine", "inherits": "fdm_machine_common", "instantiation": "true",
                             "setting_id": "X", "printable_area": ["0x0", "250x0", "250x250", "0x250"],
                             "default_print_profile": "0.20mm Standard @Kobra S1", "printer_model": "Anycubic Kobra S1"})
    put("process", "0.20mm Standard @Kobra S1", {"type": "process", "instantiation": "true", "layer_height": "0.2",
                                                 "wall_loops": "2", "compatible_printers": [PRINTER]})
    for mat, temp in (("PLA", "205"), ("PETG", "240")):
        put("filament", f"Anycubic {mat} @{PRINTER}", {
            "type": "filament", "instantiation": "true", "filament_id": "GFL99", "setting_id": "S",
            "compatible_printers": [PRINTER], "filament_type": [mat], "nozzle_temperature": [temp]})
    monkeypatch.setenv("CADSTUDIO_ORCA_PROFILES", str(root))
    monkeypatch.setattr("cadstudio.slicer.DEFAULT_VENDOR", "Anycubic")
    monkeypatch.setattr("cadstudio.slicer.DEFAULT_PRINTER", PRINTER)
    return root


def _project_cfg(path):
    with zipfile.ZipFile(path) as z:
        if "Metadata/project_settings.config" not in z.namelist():
            return None
        return json.loads(z.read("Metadata/project_settings.config"))


def test_build_merges_printer_process_and_one_filament_per_slot(profiles):
    cfg = projectconfig.build(["#ff0000", "#00ff00"], ["PLA", "PETG"], process_settings={"wall_loops": "4"})
    assert cfg["name"] == "project_settings" and cfg["from"] == "project"
    assert cfg["printer_settings_id"] == PRINTER and cfg["print_settings_id"] == "0.20mm Standard @Kobra S1"
    assert cfg["filament_settings_id"] == [f"Anycubic PLA @{PRINTER}", f"Anycubic PETG @{PRINTER}"]
    assert cfg["filament_type"] == ["PLA", "PETG"] and cfg["nozzle_temperature"] == ["205", "240"]
    assert cfg["filament_colour"] == ["#FF0000", "#00FF00"]
    assert cfg["nozzle_diameter"] == ["0.4"] and cfg["printable_height"] == "250"   # inherited machine keys
    assert cfg["wall_loops"] == "4" and cfg["layer_height"] == "0.2"
    assert len(cfg["inherits_group"]) == len(cfg["different_settings_to_system"]) == 4
    for meta in ("inherits", "instantiation", "type", "setting_id", "filament_id", "compatible_printers"):
        assert meta not in cfg
    # materials default to PLA for every slot
    assert projectconfig.build(["#111111"] * 3)["filament_type"] == ["PLA"] * 3


def test_build_without_profiles_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("CADSTUDIO_ORCA_PROFILES", str(tmp_path / "missing"))
    assert projectconfig.build(["#ffffff"]) is None


def test_multi_plate_export_is_a_project(proj, profiles):
    proj.upsert_part("a", code=DISC, filament=1, color="#1D3557")
    proj.upsert_part("b", code=DISC, filament=2, color="#E63946", plate=2)
    proj.set_print_settings(profile="functional")
    res = export_3mf(proj)
    cfg = _project_cfg(res["path"])
    assert cfg is not None
    assert cfg["filament_colour"] == ["#1D3557", "#E63946"] and cfg["wall_loops"] == "4"
    assert res["project_settings"]["printer"] == PRINTER
    assert any("Open this file as a project" in w for w in res["warnings"])
    assert not any("beside the build plate" in w for w in res["warnings"])
    res = export_3mf(proj, materials=["PETG"])
    assert _project_cfg(res["path"])["filament_type"] == ["PETG", "PETG"]


def test_single_plate_files_stay_plain(proj, profiles):
    proj.upsert_part("a", code=DISC)
    proj.upsert_part("b", code=DISC, plate=2)
    assert _project_cfg(export_3mf(proj, plate=1)["path"]) is None
    split = export_3mf(proj, split_plates=True)
    assert all(_project_cfg(p) is None for p in split["paths"])
    assert _project_cfg(export_3mf(proj, plate=1, project_settings=True)["path"]) is not None
    assert _project_cfg(export_3mf(proj, project_settings=False)["path"]) is None
    assert _project_cfg(export_3mf(proj, flavor="prusa")["path"]) is None
