# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI:
    python -m cadstudio mcp             MCP over stdio (Claude Desktop / Claude Code lokaal); start ook de editor
    python -m cadstudio web             editor + MCP-HTTP op http://127.0.0.1:8765 en open de browser
    python -m cadstudio serve           server-modus (Docker): host/poort uit CADSTUDIO_HOST/CADSTUDIO_PORT
    python -m cadstudio export [project] [--flavor orca|prusa] [--mode assembly|objects]
"""
import argparse
import os
import sys


def main() -> None:
    ap = argparse.ArgumentParser(prog="cadstudio")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("mcp")
    for name in ("web", "serve"):
        w = sub.add_parser(name)
        w.add_argument("--port", type=int, default=int(os.environ.get("CADSTUDIO_PORT", "8765")))
        w.add_argument("--host", default=os.environ.get("CADSTUDIO_HOST", "127.0.0.1" if name == "web" else "0.0.0.0"))
        w.add_argument("--no-browser", action="store_true")
    e = sub.add_parser("export")
    e.add_argument("project", nargs="?")
    e.add_argument("--flavor", default="orca", choices=["orca", "prusa"])
    e.add_argument("--mode", default="assembly", choices=["assembly", "objects"])
    e.add_argument("-o", "--output")
    a = ap.parse_args()

    if a.cmd == "mcp":
        from .mcp_server import main as run
        run()
    elif a.cmd in ("web", "serve"):
        os.environ.setdefault("CADSTUDIO_PORT", str(a.port))
        from . import links
        from .web import serve
        if a.host not in ("127.0.0.1", "localhost") and not links.token():
            print("⚠  Warning: CADSTUDIO_TOKEN is not set – anyone who can reach this port can use the editor and /mcp.",
                  file=sys.stderr)
        if a.cmd == "web" and not a.no_browser:
            import threading
            import webbrowser
            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{a.port}")).start()
        print(f"CAD-Studio: editor  {links.public_url()}\n            MCP     {links.public_url()}/mcp", file=sys.stderr)
        serve(a.host, a.port)
    elif a.cmd == "export":
        from . import project as P
        from .export3mf import export_3mf
        from .render import thumbnail
        proj = P.get_project(a.project)
        print(export_3mf(proj, a.output, mode=a.mode, flavor=a.flavor, thumbnail=thumbnail(proj)))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
