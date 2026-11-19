"""MCP server: gives Claude (Desktop / Code) tools to model parts, look at them and export 3MF.

Run:  python -m cadstudio mcp      (stdio transport, for claude_desktop_config.json)
The web editor is started automatically in a background thread (http://127.0.0.1:8765).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image

from . import links
from . import project as P
from .export3mf import export_3mf as _export_3mf, export_step as _export_step, export_stl as _export_stl
from .render import render_png, thumbnail

CHEATSHEET = (Path(__file__).parent / "cheatsheet.md").read_text(encoding="utf-8")
WEB_PORT = int(os.environ.get("CADSTUDIO_PORT", "8765"))

INSTRUCTIONS = f"""CAD-Studio: parametrische CAD (build123d / OpenCascade) voor 3D-printen, met export naar
multi-color 3MF voor Anycubic Slicer Next (Orca-basis) en de ACE Pro.

Werkwijze:
1. get_project() om de huidige staat te zien (of new_project/open_project).
2. Zet maten als parameters (set_params) zodat de gebruiker ze in de editor kan aanpassen.
3. Maak per kleur/onderdeel een part met set_part(name, code, color, filament).
   De code is build123d en moet `result` toewijzen. Lees get_build123d_reference() bij twijfel.
4. Controleer ALTIJD visueel met render_preview() en check bbox/size in het antwoord van set_part.
   Repareer fouten (de traceback komt terug) voordat je verdergaat.
5. export_3mf() voor de slicer. Geef de gebruiker de download_url en vertel welk ACE-slot welke kleur moet hebben.
Bestanden van de gebruiker (STL/3MF van MakerWorld e.d.): list_inbox() + import_mesh(file_path), of import_mesh(url=...).
De server kan op een andere machine draaien (Docker): paden zijn paden op de server, niet op de pc van de gebruiker.
De gebruiker ziet live mee in de web-editor: {{web_url}}

Korte API-samenvatting:
{CHEATSHEET[:2500]}
"""

mcp = _Server("cad-studio", instructions=INSTRUCTIONS.replace("{web_url}", links.public_url()))


def _proj() -> P.Project:
    return P.get_project()


def _part_report(proj: P.Project, name: str) -> dict:
    e = proj.build(name)
    spec = proj.find(name)
    return {"part": name, "color": spec["color"], "filament": spec["filament"], "visible": spec["visible"],
            **{k: v for k, v in e["info"].items() if k != "name"}}


# --------------------------------------------------------------------------- project tools

@mcp.tool()
def list_projects() -> dict:
    """Lijst van alle projecten en welk project actief is."""
    return {"projects": P.list_projects(), "current": P.current_project_name(), "home": str(P.HOME)}


@mcp.tool()
def new_project(name: str, notes: str = "") -> dict:
    """Maak een nieuw (leeg) project en maak het actief. Bestaat het al, dan wordt het alleen geopend."""
    P.set_current_project(name)
    proj = _proj()
    if notes:
        proj.data["notes"] = notes
        proj.save()
    return proj.summary()


@mcp.tool()
def open_project(name: str) -> dict:
    """Open een bestaand project (wordt het actieve project, ook in de web-editor)."""
    if P.slugify(name) not in P.list_projects():
        return {"error": f"Project '{name}' bestaat niet", "projects": P.list_projects()}
    P.set_current_project(name)
    return _proj().summary()


@mcp.tool()
def get_project() -> dict:
    """Volledige staat van het actieve project: parameters, alle parts met code, kleur, filament-slot
    en build-info (ok/error, bounding box, afmetingen, volume)."""
    return _proj().summary()


@mcp.tool()
def set_notes(notes: str) -> dict:
    """Sla ontwerpnotities op bij het project (eisen, maten van andere modellen, beslissingen)."""
    proj = _proj()
    proj.data["notes"] = notes
    proj.save()
    return {"ok": True}


@mcp.tool()
def set_params(params: dict[str, Any], replace: bool = False) -> dict:
    """Zet projectparameters (bv. {"w": 60, "wall": 2}). Ze zijn als variabelen beschikbaar in alle part-code
    en de gebruiker kan ze in de editor met sliders aanpassen. Waarde null verwijdert een parameter.
    Geeft de nieuwe build-status van alle parts terug."""
    proj = _proj()
    proj.set_params(params, replace=replace)
    return {"params": proj.params, "parts": [_part_report(proj, p["name"]) for p in proj.parts]}


# --------------------------------------------------------------------------- part tools

@mcp.tool()
def set_part(name: str, code: str, color: str | None = None, filament: int | None = None,
             location: list[float] | None = None, note: str | None = None) -> dict:
    """Maak of vervang een part met build123d-code. De code moet `result` toewijzen.
    color: hex, bv. "#D62828" (weergave + 3MF-kleur). filament: ACE Pro-slot / extruder 1..8.
    location: optioneel [x, y, z, rx, ry, rz] die ná de code wordt toegepast.
    Antwoord bevat ok/error (+traceback), bbox, size (mm), volume en aantal driehoeken."""
    proj = _proj()
    proj.upsert_part(name, type="code", code=code, color=color, filament=filament, location=location, note=note)
    return _part_report(proj, name)


@mcp.tool()
def update_part(name: str, color: str | None = None, filament: int | None = None, visible: bool | None = None,
                export: bool | None = None, location: list[float] | None = None, new_name: str | None = None) -> dict:
    """Wijzig eigenschappen van een part zonder de code te vervangen (kleur, slot, zichtbaarheid,
    meenemen in export, positie/rotatie [x,y,z,rx,ry,rz], hernoemen – verwijzingen part("..") worden meegenomen)."""
    proj = _proj()
    proj.find(name)
    proj.upsert_part(name, color=color, filament=filament, visible=visible, export=export, location=location)
    if new_name and new_name != name:
        proj.rename_part(name, new_name)
        name = new_name
    return _part_report(proj, name)


@mcp.tool()
def add_primitive(name: str, kind: str, size: list[float], position: list[float] | None = None,
                  color: str | None = None, filament: int | None = None, text: str | None = None) -> dict:
    """Snel een basisvorm toevoegen (genereert build123d-code die je later kunt aanpassen).
    kind: box [l,w,h] | cylinder [r,h] | sphere [r] | cone [r1,r2,h] | torus [R,r] | text [font_size, depth] (+text).
    De vorm staat op z=0 (onderkant op het bed), position = [x,y,z] verschuiving."""
    k = kind.lower()
    s = list(size) + [0, 0, 0]
    on_bed = "align=(Align.CENTER, Align.CENTER, Align.MIN)"
    if k == "box":
        code = f"result = Box({s[0]}, {s[1]}, {s[2]}, {on_bed})"
    elif k == "cylinder":
        code = f"result = Cylinder({s[0]}, {s[1]}, {on_bed})"
    elif k == "sphere":
        code = f"result = Pos(0, 0, {s[0]}) * Sphere({s[0]})"
    elif k == "cone":
        code = f"result = Cone({s[0]}, {s[1]}, {s[2]}, {on_bed})"
    elif k == "torus":
        code = f"result = Pos(0, 0, {s[1]}) * Torus({s[0]}, {s[1]})"
    elif k == "text":
        code = f"result = extrude(Text({json.dumps(text or name)}, font_size={s[0] or 10}), amount={s[1] or 2})"
    else:
        return {"error": f"Onbekend kind '{kind}'"}
    loc = None
    if position:
        loc = (list(position) + [0, 0, 0])[:3] + [0, 0, 0]
    return set_part(name, code, color=color, filament=filament, location=loc)


@mcp.tool()
def delete_part(name: str) -> dict:
    """Verwijder een part."""
    proj = _proj()
    proj.delete_part(name)
    return {"ok": True, "parts": [p["name"] for p in proj.parts]}


@mcp.tool()
def list_inbox() -> dict:
    """Bestanden in de inbox-map van de server (daar zet de gebruiker STL/3MF/OBJ-bestanden neer,
    bv. via de editor-upload, een netwerkshare of FileBrowser). Gebruik de naam in import_mesh(file_path=...)."""
    d = links.inbox_dir()
    files = [{"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
             for f in sorted(d.iterdir()) if f.is_file() and f.suffix.lower() in (".stl", ".3mf", ".obj", ".ply", ".glb")]
    return {"inbox": str(d), "files": files}


@mcp.tool()
def import_mesh(name: str, file_path: str | None = None, url: str | None = None, color: str | None = None,
                filament: int | None = None, location: list[float] | None = None) -> dict:
    """Importeer een STL/3MF/OBJ als referentie-part (bv. een model van MakerWorld om tegenaan te ontwerpen).
    file_path: bestandsnaam in de inbox (zie list_inbox) of een absoluut pad op de server.
    url: directe download-URL van het bestand.
    Het model wordt gecentreerd op X/Y en op z=0 gezet. Mesh-parts worden getoond, gemeten en meegeëxporteerd,
    maar kunnen niet in booleans gebruikt worden. Zet export op false als het alleen ter referentie is."""
    proj = _proj()
    if url:
        import tempfile
        import urllib.request
        suffix = Path(url.split("?")[0]).suffix or ".stl"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CAD-Studio"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read(300 * 1024 * 1024 + 1)
        except Exception as e:
            return {"error": f"Download mislukt: {e}. Tip: MakerWorld/Printables vereisen inloggen; laat de gebruiker "
                             f"het bestand dan in de inbox zetten of uploaden in de editor."}
        if len(data) > 300 * 1024 * 1024:
            return {"error": "bestand groter dan 300 MB"}
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
        src = Path(tmp.name)
    elif file_path:
        src = Path(file_path)
        if not src.is_absolute():
            src = links.inbox_dir() / file_path
    else:
        return {"error": "geef file_path of url"}
    try:
        proj.import_mesh(name, src, color=color, filament=filament)
    finally:
        if url:
            src.unlink(missing_ok=True)
    if location:
        proj.upsert_part(name, location=location)
    return _part_report(proj, name)


@mcp.tool()
def measure(names: list[str] | None = None) -> dict:
    """Bounding boxes, afmetingen en volumes van parts (alle parts als names leeg is), plus de totale
    bounding box en of het op het bed (250x250x250) past."""
    proj = _proj()
    names = names or [p["name"] for p in proj.parts]
    reps = [_part_report(proj, n) for n in names]
    ok = [r for r in reps if r.get("ok")]
    total = None
    if ok:
        lo = [min(r["bbox_min"][i] for r in ok) for i in range(3)]
        hi = [max(r["bbox_max"][i] for r in ok) for i in range(3)]
        size = [round(hi[i] - lo[i], 3) for i in range(3)]
        total = {"bbox_min": lo, "bbox_max": hi, "size": size,
                 "fits_bed": all(size[i] <= P.BED[i] for i in range(3))}
    return {"parts": reps, "total": total}


@mcp.tool()
def render_preview(view: str = "grid", parts: list[str] | None = None) -> Image:
    """Render een afbeelding van het model zodat je het resultaat kunt controleren.
    view: grid (iso/front/top/right) | iso | front | back | left | right | top | bottom | iso_back.
    parts: alleen deze parts tonen (standaard alle zichtbare)."""
    png, errors = render_png(_proj(), view=view, parts=parts)
    if errors:
        print("render errors: " + "; ".join(errors), file=sys.stderr)
    return Image(data=png, format="png")


# --------------------------------------------------------------------------- export tools

@mcp.tool()
def export_3mf(filename: str | None = None, mode: str = "assembly", flavor: str = "orca",
               parts: list[str] | None = None) -> dict:
    """Exporteer naar 3MF.
    mode: "assembly" = alle parts als één object met een extruder/ACE-slot per part (multi-color print);
          "objects"  = elk part een los object.
    flavor: "orca" (Anycubic Slicer Next, OrcaSlicer, Bambu Studio) of "prusa" (PrusaSlicer).
    filename: optioneel pad; standaard <project>/exports/<project>.3mf.
    Antwoord bevat het pad en welke parts op welk filament-slot staan."""
    proj = _proj()
    res = _export_3mf(proj, filename, mode=mode, flavor=flavor, only=parts, thumbnail=thumbnail(proj))
    res["download_url"] = links.download_url(res["path"])
    return res


@mcp.tool()
def export_stl(filename: str | None = None, separate: bool = True, parts: list[str] | None = None) -> dict:
    """Exporteer STL (per part een bestand, of samengevoegd met separate=False)."""
    res = _export_stl(_proj(), filename, only=parts, separate=separate)
    res["download_urls"] = [links.download_url(f) for f in res["files"]]
    return res


@mcp.tool()
def export_step(filename: str | None = None, parts: list[str] | None = None) -> dict:
    """Exporteer de CAD-parts als STEP (exacte geometrie, te openen in Fusion 360 / FreeCAD)."""
    res = _export_step(_proj(), filename, only=parts)
    res["download_url"] = links.download_url(res["path"])
    return res


# --------------------------------------------------------------------------- help / UI

@mcp.tool()
def get_build123d_reference() -> str:
    """Spiekbrief build123d + printbaarheidsregels + multi-color werkwijze. Lees dit vóór je complexe code schrijft."""
    return CHEATSHEET


@mcp.tool()
def open_editor() -> dict:
    """Geef de URL van de web-editor (live meekijken en zelf bewerken) en open hem als de server lokaal draait."""
    url = links.public_url()
    if os.environ.get("CADSTUDIO_IN_DOCKER") != "1":
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return {"url": url}


# --------------------------------------------------------------------------- entry point

def _start_web_in_background() -> None:
    import socket

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", WEB_PORT)) == 0:
            return  # already running (e.g. started separately)
    from .web import serve

    t = threading.Thread(target=serve, kwargs={"port": WEB_PORT, "quiet": True}, daemon=True)
    t.start()


def main() -> None:
    # Protect the stdio JSON-RPC channel: anything printed to fd 1 by libraries (OCCT, fonts, user code)
    # would corrupt it. Keep a private copy of the real stdout for MCP and point fd 1 at stderr.
    real_stdout = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = os.fdopen(real_stdout, "w", buffering=1, encoding="utf-8")

    P.ensure_demo()
    if os.environ.get("CADSTUDIO_NO_WEB") != "1":
        try:
            _start_web_in_background()
        except Exception as e:  # never let the UI break the MCP server
            print(f"web UI niet gestart: {e}", file=sys.stderr)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
