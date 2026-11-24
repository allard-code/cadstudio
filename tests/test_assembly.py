# SPDX-License-Identifier: GPL-3.0-or-later
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cadstudio import project as P
from cadstudio.render import clip_triangles, render_assembly_png

from .conftest import BOX

# closed box, hollow inside: the item in it is only visible see-through or in a section
SHELL = ("result = Box(40, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))"
         " - Pos(0, 0, 2) * Box(36, 26, 16, align=(Align.CENTER, Align.CENTER, Align.MIN))")


def _px(png, pred):
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    return int(pred(a[..., 0], a[..., 1], a[..., 2]).sum())


def _orange(r, g, b):  # also when seen through a blue see-through shell
    return (r > 110) & (r > b + 30) & (r > g + 15)


def _red(r, g, b):
    return (r > 170) & (g < 90) & (b < 90)


@pytest.fixture
def asm(proj):
    proj.upsert_part("shell", code=SHELL)
    proj.upsert_assembly_item("kast", code='result = part("shell")', color="#3A86D4")
    proj.upsert_assembly_item("binnen", code="result = Pos(0, 0, 8) * Cylinder(6, 10)", color="#E07A1F")
    return proj


def test_items_build_and_stay_out_of_plates_and_exports(asm):
    s = asm.summary()
    assert [a["name"] for a in s["assembly"]] == ["kast", "binnen"]
    assert all(a["info"]["ok"] for a in s["assembly"])
    assert [p["name"] for p in s["parts"]] == ["shell"]
    assert [spec["name"] for spec, _, _ in P.exportable_meshes(asm)] == ["shell"]


def test_item_rebuilds_when_referenced_part_changes(asm):
    k1 = asm.build_assembly_item("kast")["info"]["size"]
    asm.upsert_part("shell", code=BOX)
    assert asm.build_assembly_item("kast")["info"]["size"] != k1


def test_user_code_errors_are_reported(asm):
    asm.upsert_assembly_item("kapot", code="result = 1/0")
    info = asm.build_assembly_item("kapot")["info"]
    assert info["ok"] is False and "ZeroDivisionError" in info["error"]
    _, errors = render_assembly_png(asm)
    assert errors and "kapot" in errors[0]


def test_rename_part_updates_assembly_and_checkpoint_keeps_it(asm):
    asm.rename_part("shell", "huis")
    assert 'part("huis")' in asm.find_assembly_item("kast")["code"]
    asm.save_checkpoint("cp")
    asm.delete_assembly_item("binnen")
    asm.restore_checkpoint("cp")
    assert [a["name"] for a in asm.assembly] == ["kast", "binnen"]


def test_ghost_shows_whats_inside(asm):
    hidden, _ = render_assembly_png(asm, view="iso", size=400, ghost=[])
    seen, _ = render_assembly_png(asm, view="iso", size=400, ghost=["kast"])
    assert _px(seen, _orange) > _px(hidden, _orange) + 2000


def test_section_draws_cut_faces_red(asm):
    plain, _ = render_assembly_png(asm, view="iso", size=400, ghost=[])
    cut, _ = render_assembly_png(asm, view="iso", size=400, ghost=[], section="y")
    assert _px(plain, _red) < 50 and _px(cut, _red) > 1000
    with pytest.raises(ValueError):
        render_assembly_png(asm, section="q")


def test_explode_moves_items_apart(asm):
    asm.upsert_assembly_item("deksel", code="result = Pos(0, 0, 21) * Box(40, 30, 2)", explode=[0, 0, 30])
    png, _ = render_assembly_png(asm, view="front", size=400, explode=1.0)
    img = Image.open(io.BytesIO(png))
    assert img.size == (400, 434)
    assert "explode" in asm.find_assembly_item("deksel") and asm.find_assembly_item("deksel")["explode"] == [0, 0, 30]


def test_empty_assembly_is_an_error(proj):
    with pytest.raises(ValueError, match="empty"):
        render_assembly_png(proj)


def test_clip_triangles_splits_crossing_triangles():
    tri = np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]]], dtype=float)
    out = clip_triangles(tri, 0, 5.0)
    assert out[:, :, 0].max() <= 5.0 + 1e-9
    area = sum(np.linalg.norm(np.cross(t[1] - t[0], t[2] - t[0])) / 2 for t in out)
    assert area == pytest.approx(50 - 12.5)
    assert len(clip_triangles(tri, 0, -1.0)) == 0
    assert len(clip_triangles(tri, 0, -1.0, keep_above=True)) == 1


def test_web_endpoints(asm):
    from cadstudio.web import app

    c = TestClient(app)
    r = c.put("/api/assembly/deksel", json={"code": "result = Pos(0, 0, 21) * Box(40, 30, 2)", "ghost": True})
    assert r.status_code == 200 and any(a["name"] == "deksel" and a["ghost"] for a in r.json()["assembly"])
    m = c.get("/api/assembly/mesh/deksel")
    nv, nt = np.frombuffer(m.content[:8], dtype=np.uint32)
    assert nv > 0 and nt > 0
    png = c.get("/api/assembly.png", params={"view": "iso", "ghost": "kast", "section": "x", "size": 400})
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    dl = c.get("/api/assembly.png", params={"view": "top", "download": True, "size": 400})
    assert "attachment" in dl.headers["content-disposition"]
    assert (asm.dir / "exports" / f"{asm.name}-assembly-top.png").exists()
    assert c.delete("/api/assembly/deksel").status_code == 200
    assert c.get("/api/assembly.png", params={"section": "q"}).status_code == 422
