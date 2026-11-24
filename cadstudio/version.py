# SPDX-License-Identifier: GPL-3.0-or-later
"""Which build is running, and (best effort) whether a newer one is published.

The Docker image gets the commit and build date as build args (CADSTUDIO_COMMIT, CADSTUDIO_BUILD_DATE).
The update check asks GitHub for the newest commit on the default branch of CADSTUDIO_UPDATE_REPO
(default allard-code/cadstudio), cached for an hour; set CADSTUDIO_UPDATE_CHECK=0 to turn it off.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

from . import __version__

_CACHE: dict = {"at": 0.0, "data": None}
_LOCK = threading.Lock()
_TTL = 3600


def orca_version() -> str | None:
    from . import slicer
    if not slicer.available():
        return None
    return os.environ.get("CADSTUDIO_ORCA_VERSION") or "installed"


def _latest_commit(repo: str, timeout: float = 4.0) -> dict | None:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/HEAD",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "cadstudio"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https URL)
        d = json.loads(r.read().decode())
    return {"commit": d["sha"], "date": d.get("commit", {}).get("committer", {}).get("date")}


def latest(force: bool = False) -> dict | None:
    if os.environ.get("CADSTUDIO_UPDATE_CHECK", "1") == "0":
        return None
    with _LOCK:
        if not force and _CACHE["data"] is not None and time.time() - _CACHE["at"] < _TTL:
            return _CACHE["data"]
    repo = os.environ.get("CADSTUDIO_UPDATE_REPO", "allard-code/cadstudio")
    try:
        data = _latest_commit(repo)
    except Exception as e:  # offline, rate limited, ...: report it, don't fail the page
        data = {"error": type(e).__name__}
    with _LOCK:
        _CACHE.update(at=time.time(), data=data)
    return data


def info(check_updates: bool = True) -> dict:
    commit = os.environ.get("CADSTUDIO_COMMIT", "") or None
    res = {"version": __version__, "commit": commit, "short": commit[:7] if commit else None,
           "built": os.environ.get("CADSTUDIO_BUILD_DATE") or None, "orcaslicer": orca_version()}
    if check_updates and commit:
        lat = latest()
        if lat and "commit" in lat:
            res["latest_commit"] = lat["commit"][:7]
            res["up_to_date"] = lat["commit"] == commit
        elif lat:
            res["update_check_error"] = lat.get("error")
    return res
