# SPDX-License-Identifier: GPL-3.0-or-later
from cadstudio import __version__
from cadstudio import version as V


def test_local_build_has_no_commit_and_skips_the_update_check(monkeypatch):
    monkeypatch.delenv("CADSTUDIO_COMMIT", raising=False)
    called = []
    monkeypatch.setattr(V, "_latest_commit", lambda repo: called.append(repo))
    info = V.info()
    assert info["version"] == __version__ and info["commit"] is None and "up_to_date" not in info
    assert called == []


def test_up_to_date_and_update_available(monkeypatch):
    monkeypatch.setenv("CADSTUDIO_COMMIT", "a" * 40)
    monkeypatch.setenv("CADSTUDIO_BUILD_DATE", "2026-11-24T10:00:00Z")
    monkeypatch.setattr(V, "_latest_commit", lambda repo: {"commit": "a" * 40, "date": None})
    info = V.latest(force=True) and V.info()
    assert info["short"] == "aaaaaaa" and info["up_to_date"] is True and info["built"] == "2026-11-24T10:00:00Z"
    monkeypatch.setattr(V, "_latest_commit", lambda repo: {"commit": "b" * 40, "date": None})
    V.latest(force=True)
    info = V.info()
    assert info["up_to_date"] is False and info["latest_commit"] == "bbbbbbb"


def test_offline_or_disabled(monkeypatch):
    monkeypatch.setenv("CADSTUDIO_COMMIT", "a" * 40)

    def boom(repo):
        raise OSError("offline")
    monkeypatch.setattr(V, "_latest_commit", boom)
    V.latest(force=True)
    assert V.info()["update_check_error"] == "OSError"
    monkeypatch.setenv("CADSTUDIO_UPDATE_CHECK", "0")
    info = V.info()
    assert "up_to_date" not in info and "update_check_error" not in info
