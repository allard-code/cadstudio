# SPDX-License-Identifier: GPL-3.0-or-later
"""Every test session gets its own CADSTUDIO_HOME, set *before* cadstudio is imported."""
import itertools
import os
import tempfile

os.environ["CADSTUDIO_HOME"] = tempfile.mkdtemp(prefix="cadstudio-test-")
os.environ.pop("CADSTUDIO_TOKEN", None)

import pytest  # noqa: E402

from cadstudio import project as P  # noqa: E402

_n = itertools.count()


@pytest.fixture
def proj():
    """A fresh, active, empty project."""
    name = f"t{next(_n)}"
    P.set_current_project(name)
    return P.get_project(name)


BOX = "result = Box(20, 10, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))"
