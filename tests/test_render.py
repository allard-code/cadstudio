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
