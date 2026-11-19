# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings for running as a (remote) server: public URL, access token, signed download links, inbox."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from . import project as P


def token() -> str | None:
    """CADSTUDIO_TOKEN protects the web editor and /mcp. Unset = no auth (only for localhost use!)."""
    t = os.environ.get("CADSTUDIO_TOKEN", "").strip()
    return t or None


def public_url() -> str:
    url = os.environ.get("CADSTUDIO_PUBLIC_URL", "").strip().rstrip("/")
    return url or f"http://localhost:{os.environ.get('CADSTUDIO_PORT', '8765')}"


def inbox_dir() -> Path:
    d = P.HOME / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _secret() -> bytes:
    f = P.HOME / ".link_secret"
    if not f.exists():
        P.HOME.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip().encode()


def _sig(rel: str, exp: int) -> str:
    return hmac.new(_secret(), f"{rel}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def download_url(path: str | Path, hours: int = 72) -> str | None:
    """Signed, expiring link to a file inside the projects folder (works without the token)."""
    p = Path(path).resolve()
    root = P.PROJECTS.resolve()
    if root not in p.parents:
        return None
    rel = p.relative_to(root).as_posix()
    exp = int(time.time()) + hours * 3600
    return f"{public_url()}/dl/{exp}/{_sig(rel, exp)}/{quote(rel)}"


def check_download(exp: int, sig: str, rel: str) -> Path | None:
    if exp < time.time() or not hmac.compare_digest(sig, _sig(rel, exp)):
        return None
    p = (P.PROJECTS / rel).resolve()
    if P.PROJECTS.resolve() not in p.parents or not p.is_file():
        return None
    return p
