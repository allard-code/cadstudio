# SPDX-License-Identifier: GPL-3.0-or-later
"""Hand a sliced plate to Home Assistant so it can start the print.

CAD-Studio uploads the G-code to Home Assistant's file upload endpoint (/api/file_upload, the same one the
"file" selector in the UI uses) and gets a file id back. It then fires an event (default
`cadstudio_print_request`) carrying that id plus what the G-code needs (material, print time, grams).
An automation in Home Assistant reacts to the event - e.g. asks on your phone which ACE/AMS slot to use and
then calls the printer integration's print action (anycubic_cloud.print_and_upload_no_cloud_save, ...) with
`uploaded_gcode_file: <file_id>`.

Settings (environment):
  CADSTUDIO_HA_URL    e.g. http://192.168.1.10:8123
  CADSTUDIO_HA_TOKEN  long-lived access token of an *admin* user (file upload is admin-only)
  CADSTUDIO_HA_EVENT  event type to fire (default: cadstudio_print_request)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_EVENT = "cadstudio_print_request"


class HomeAssistantError(RuntimeError):
    pass


def settings() -> tuple[str, str, str]:
    url = os.environ.get("CADSTUDIO_HA_URL", "").strip().rstrip("/")
    token = os.environ.get("CADSTUDIO_HA_TOKEN", "").strip()
    event = os.environ.get("CADSTUDIO_HA_EVENT", "").strip() or DEFAULT_EVENT
    return url, token, event


def configured() -> bool:
    url, token, _ = settings()
    return bool(url and token)


def _request(req: urllib.request.Request, timeout: int) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL comes from the admin's env)
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        hint = ""
        if e.code == 401:
            hint = " - check CADSTUDIO_HA_TOKEN"
        elif e.code == 403:
            hint = " - the token must belong to an admin user (file upload is admin-only)"
        raise HomeAssistantError(f"Home Assistant answered HTTP {e.code} on {req.full_url}{hint}. {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise HomeAssistantError(f"Cannot reach Home Assistant at {req.full_url}: {e}") from e
    try:
        return json.loads(body) if body.strip() else {}
    except ValueError:
        return {"raw": body[:300]}


def upload_file(path: Path, timeout: int = 120) -> str:
    """POST the file to /api/file_upload (multipart field 'file'); returns Home Assistant's file id."""
    url, token, _ = settings()
    boundary = f"----cadstudio{secrets.token_hex(12)}"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode()
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{url}/api/file_upload", data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "CAD-Studio"})
    res = _request(req, timeout)
    file_id = res.get("file_id")
    if not file_id:
        raise HomeAssistantError(f"Home Assistant did not return a file_id: {res}")
    return str(file_id)


def fire_event(data: dict, event_type: str | None = None, timeout: int = 30) -> str:
    url, token, default_event = settings()
    event_type = event_type or default_event
    req = urllib.request.Request(f"{url}/api/events/{event_type}", data=json.dumps(data).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "User-Agent": "CAD-Studio"})
    _request(req, timeout)
    return event_type


def gcode_materials(gcode: Path) -> list[str]:
    """Filament types per extruder from OrcaSlicer's config block ('; filament_type = PLA;PETG')."""
    try:
        with open(gcode, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 400_000))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    m = re.search(r"^;\s*filament_type\s*=\s*(.+)$", text, re.M)
    return [t.strip() for t in m.group(1).split(";") if t.strip()] if m else []
