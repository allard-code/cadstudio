# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end: start `cadstudio serve` in a subprocess and talk MCP over streamable HTTP."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

try:
    from mcp.client.streamable_http import streamablehttp_client as http_client
except ImportError:  # MCP SDK 2.x
    from mcp.client.streamable_http import streamable_http_client as http_client
from mcp import ClientSession


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, CADSTUDIO_HOME=str(tmp_path_factory.mktemp("mcp")), CADSTUDIO_PORT=str(port),
               CADSTUDIO_PUBLIC_URL=f"http://127.0.0.1:{port}", CADSTUDIO_TOKEN="tok")
    proc = subprocess.Popen([sys.executable, "-m", "cadstudio", "serve", "--host", "127.0.0.1"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield f"http://127.0.0.1:{port}/mcp?token=tok"
    proc.terminate()
    proc.wait(10)


def _text(res):
    return json.loads(next(c.text for c in res.content if c.type == "text"))


def test_mcp_round_trip(server):
    async def run():
        async with http_client(server) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                assert {"set_part", "render_preview", "export_3mf", "import_mesh", "check_floating", "slice_plate"} <= tools
                await s.call_tool("new_project", {"name": "e2e"})
                rep = _text(await s.call_tool("set_part", {"name": "a", "code": "result = Box(10, 10, 10)", "color": "#D62828"}))
                assert rep["ok"] and rep["watertight"]
                bad = _text(await s.call_tool("set_part", {"name": "b", "code": "result = Box(1)"}))
                assert bad["ok"] is False and "traceback" in bad
                await s.call_tool("delete_part", {"name": "b"})
                fl = _text(await s.call_tool("check_floating", {}))
                assert fl["ok"] and fl["plates"]["1"]["floating"] == []
                img = await s.call_tool("render_preview", {"view": "iso"})
                assert img.content[0].type == "image"
                exp = _text(await s.call_tool("export_3mf", {}))
                with urllib.request.urlopen(exp["download_url"]) as r:  # signed link, no token needed
                    assert r.read(2) == b"PK"
        return True

    assert asyncio.run(run())
