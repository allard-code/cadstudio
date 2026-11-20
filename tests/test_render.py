# SPDX-License-Identifier: GPL-3.0-or-later
import io

import numpy as np
from PIL import Image

from cadstudio.render import render_png

from .conftest import BOX


def test_render_grid_and_single_view(proj):
    proj.upsert_part("a", code=BOX, color="#D62828")
    png, errors = render_png(proj)
    img = Image.open(io.BytesIO(png))
    assert img.size[0] == 1000 and not errors
    # the red part is actually drawn
    a = np.asarray(img.convert("RGB")).astype(int)
    assert ((a[..., 0] > 150) & (a[..., 1] < 90) & (a[..., 2] < 90)).sum() > 1000
    png, _ = render_png(proj, view="top", size=300)
    assert Image.open(io.BytesIO(png)).size == (300, 334)


def test_render_reports_broken_parts(proj):
    proj.upsert_part("ok", code=BOX)
    proj.upsert_part("broken", code="result = 1/0")
    _, errors = render_png(proj)
    assert errors and "broken" in errors[0]


def _orange_pixels(png):
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    return ((a[..., 0] > 180) & (a[..., 1] > 60) & (a[..., 1] < 160) & (a[..., 2] < 80)).sum()


def test_overhangs_highlights_floating_underside(proj):
    # bottom face sits at z=20-2.5=17.5, well above the bed -> its flat underside is an unsupported overhang
    proj.upsert_part("floater", code=BOX, location=[0, 0, 20, 0, 0, 0], color="#2266cc")
    png, _ = render_png(proj, view="bottom", size=300, overhangs=True)
    assert _orange_pixels(png) > 500
    # without the flag, no (or only stray antialiasing) orange tint is applied
    png_off, _ = render_png(proj, view="bottom", size=300, overhangs=False)
    assert _orange_pixels(png_off) < 20


def test_overhangs_ignores_faces_resting_on_bed(proj):
    # default BOX already rests on the bed (align z=MIN) - its bottom face must not be flagged
    proj.upsert_part("grounded", code=BOX, color="#2266cc")
    png, _ = render_png(proj, view="bottom", size=300, overhangs=True)
    assert _orange_pixels(png) < 20
