# SPDX-License-Identifier: GPL-3.0-or-later
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest

from cadstudio import slicer
from cadstudio.export3mf import export_3mf

PRINTER = "Acme P1 0.4 nozzle"


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    """A tiny OrcaSlicer-style vendor tree with an inheritance chain per preset type."""
    root = tmp_path / "profiles"
    files = {
        "machine/fdm_machine_common.json": {"name": "fdm_machine_common", "gcode_flavor": "marlin", "a": "base"},
        f"machine/{PRINTER}.json": {"name": PRINTER, "inherits": "fdm_machine_common", "gcode_flavor": "klipper",
                                    "default_print_profile": f"0.20mm Standard @{PRINTER}"},
        "process/fdm_process_common.json": {"name": "fdm_process_common", "wall_loops": "2", "layer_height": "0.2",
                                            "instantiation": "false"},
        f"process/0.20mm Standard @{PRINTER}.json": {"name": f"0.20mm Standard @{PRINTER}",
                                                     "inherits": "fdm_process_common",
                                                     "compatible_printers": [PRINTER]},
        "filament/fdm_filament_pla.json": {"name": "fdm_filament_pla", "filament_type": ["PLA"],
                                           "instantiation": "false"},
        f"filament/Acme PLA @{PRINTER}.json": {"name": f"Acme PLA @{PRINTER}", "inherits": "fdm_filament_pla",
                                               "compatible_printers": [PRINTER]},
        f"filament/Acme PETG @{PRINTER}.json": {"name": f"Acme PETG @{PRINTER}", "compatible_printers": [PRINTER]},
    }
    for rel, data in files.items():
        p = root / "Acme" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))
    monkeypatch.setenv("CADSTUDIO_ORCA_PROFILES", str(root))
    return root


def test_flatten_merges_the_inheritance_chain(profiles):
    m = slicer.flatten("machine", PRINTER, vendor="Acme")
    assert m["gcode_flavor"] == "klipper" and m["a"] == "base" and m["inherits"] == ""
    p = slicer.flatten("process", f"0.20mm Standard @{PRINTER}", vendor="Acme")
    assert p["wall_loops"] == "2" and p["name"] == f"0.20mm Standard @{PRINTER}"
    with pytest.raises(slicer.SlicerError, match="not found"):
        slicer.flatten("machine", "Nope", vendor="Acme")


def test_material_names_resolve_to_printer_presets(profiles):
    assert slicer.default_process(PRINTER, vendor="Acme") == f"0.20mm Standard @{PRINTER}"
    assert slicer.filament_preset("PLA", PRINTER, vendor="Acme") == f"Acme PLA @{PRINTER}"
    assert slicer.filament_preset("petg", PRINTER, vendor="Acme") == f"Acme PETG @{PRINTER}"
    with pytest.raises(slicer.SlicerError, match="No Acme filament preset"):
        slicer.filament_preset("TPU", PRINTER, vendor="Acme")
    assert slicer.list_presets("process", vendor="Acme", printer=PRINTER) == [f"0.20mm Standard @{PRINTER}"]


def test_override_formatting():
    assert slicer._fmt_value("sparse_infill_density", 20) == "20%"
    assert slicer._fmt_value("enable_support", True) == "1"
    assert slicer._fmt_value("wall_loops", 4) == "4"


def test_gcode_statistics_are_parsed(tmp_path):
    g = tmp_path / "x.gcode"
    g.write_text("; HEADER_BLOCK_START\n; total layer number: 50\nG1 X0\n" + "G1 X1\n" * 1000 +
                 "; filament used [mm] = 1234.5\n; filament used [g] = 3.61\n"
                 "; estimated printing time (normal mode) = 14m 31s\n")
    st = slicer._parse_gcode_stats(g)
    assert st == {"print_time": "14m 31s", "filament_g": 3.6, "filament_mm": "1234.5", "layers": "50"}


def test_cube_3mf_is_a_closed_mesh(tmp_path):
    import trimesh
    m = trimesh.load(slicer.write_cube_3mf(tmp_path / "c.3mf"), force="mesh")
    assert m.is_watertight and abs(m.volume - 8000) < 1e-6


def test_slicing_without_orca_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CADSTUDIO_ORCA", str(tmp_path / "missing"))
    monkeypatch.setattr(slicer, "ORCA_HOME", tmp_path / "none")
    monkeypatch.setattr(slicer.shutil, "which", lambda _: None)
    assert slicer.orca_binary() is None and not slicer.available()
    with pytest.raises(slicer.SlicerError, match="not installed"):
        slicer.slice_3mf(slicer.write_cube_3mf(tmp_path / "c.3mf"), tmp_path)


def test_export_filament_map_renumbers_slots(proj):
    proj.upsert_part("a", code="result = Box(10, 10, 2)", filament=1)
    proj.upsert_part("b", code="result = Pos(20, 0, 0) * Box(10, 10, 2)", filament=2)
    res = export_3mf(proj, mode="assembly", plate=1, filament_map={1: 1, 2: 1})
    assert set(res["filament_slots"]) == {"1"}
    with zipfile.ZipFile(res["path"]) as z:
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    assert {p.find("metadata[@key='extruder']").get("value") for p in cfg.iter("part")} == {"1"}
