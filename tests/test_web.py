# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from fastapi.testclient import TestClient

from cadstudio import links
from cadstudio.web import app

from .conftest import BOX


@pytest.fixture(scope="module")
def client():
    # the MCP session manager can only be started once per process
    with TestClient(app) as c:
        yield c


def test_open_without_token(client, proj, monkeypatch):
    monkeypatch.delenv("CADSTUDIO_TOKEN", raising=False)
    assert client.get("/").status_code == 200
    r = client.put("/api/parts/a", json={"code": BOX, "color": "#00FF00"})
    assert r.status_code == 200
    part = next(p for p in r.json()["parts"] if p["name"] == "a")
    assert part["info"]["ok"]
    mesh = client.get("/api/mesh/a").content
    assert len(mesh) > 8


def test_token_auth(client, monkeypatch):
    client.cookies.clear()
    monkeypatch.setenv("CADSTUDIO_TOKEN", "s3cret")
    assert client.get("/health").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/project").status_code == 401
    assert client.post("/mcp", json={}).status_code == 401
    assert "token" in client.get("/").text  # login page
    assert client.get("/api/project", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/project", headers={"x-api-key": "s3cret"}).status_code == 200
    assert client.get("/api/project", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/project", headers={"Authorization": "s3cret"}).status_code == 200  # bare token
    assert client.get("/api/project", headers={"Authorization": "Basic s3cret"}).status_code == 401
    # no OAuth: discovery endpoints say "not found", not "unauthorized"
    assert client.get("/.well-known/oauth-protected-resource/mcp").status_code == 404
    assert client.get("/.well-known/oauth-authorization-server").status_code == 404
    # form login sets a cookie
    r = client.post("/login", data={"token": "s3cret"}, follow_redirects=False)
    assert r.status_code == 303 and "cs_token" in r.cookies
    client.cookies.set("cs_token", "s3cret")
    assert client.get("/api/project").status_code == 200


def test_signed_download(client, proj, monkeypatch):
    monkeypatch.delenv("CADSTUDIO_TOKEN", raising=False)
    proj.upsert_part("a", code=BOX)
    res = client.post("/api/export", json={"format": "3mf"}).json()
    url = res["download"][0]
    monkeypatch.setenv("CADSTUDIO_TOKEN", "s3cret")  # downloads work without the token…
    client.cookies.clear()
    r = client.get(url)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    parts = url.split("/")
    parts[3] = "0" * len(parts[3])  # …but not with a tampered signature
    assert client.get("/".join(parts)).status_code == 404


def test_download_link_rejects_paths_outside_projects(tmp_path):
    outside = tmp_path / "x.txt"
    outside.write_text("x")
    assert links.download_url(outside) is None


def test_version_endpoint(client, monkeypatch):
    monkeypatch.delenv("CADSTUDIO_TOKEN", raising=False)
    monkeypatch.delenv("CADSTUDIO_COMMIT", raising=False)
    from cadstudio import __version__
    v = client.get("/api/version").json()
    assert v["version"] == __version__ and v["commit"] is None
    assert client.get("/health").json()["version"] == __version__
