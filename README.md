# CAD-Studio

[![CI](https://github.com/allard-code/cadstudio/actions/workflows/ci.yml/badge.svg)](https://github.com/allard-code/cadstudio/actions/workflows/ci.yml)
[![Docker](https://github.com/allard-code/cadstudio/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/allard-code/cadstudio/pkgs/container/cadstudio)
[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)

🇳🇱 [Nederlandse versie](README.nl.md)

**CAD-Studio** is a self-hosted parametric CAD editor with an **MCP server**, so Claude can design 3D-printable parts for you, check them visually and export them as **multi-colour 3MF**. The 3MF works in Orca-based slicers (OrcaSlicer, Bambu Studio, Anycubic Slicer Next) and in PrusaSlicer. Geometry is real B-rep CAD (build123d on OpenCASCADE), not meshes.

![CAD-Studio editor](docs/screenshot.png)

```
 Claude Code / Desktop / claude.ai ──MCP (HTTP /mcp)──►┐
                                                       │  CAD-Studio container ── /data (projects, exports, inbox)
 you, anywhere (browser, phone)    ──https (editor /)──►┘
```

- **Claude designs, you watch live.** Changes from Claude appear instantly in the browser editor, and you can tweak parameters, colours, code and position yourself.
- **Parametric.** Dimensions are project parameters with sliders. Every part is a short build123d script.
- **Claude can see its work.** `render_preview` returns a 4-view render, so Claude can check orientation, text and inlays.
- **Assembly view.** Show how the printed parts go together: see-through shells, section cuts and an exploded view, in the editor and as a PNG.
- **Multi-colour for AMS / ACE Pro / MMU.** One part per colour, each with its own filament slot. The export gives one object with a per-part extruder assignment.
- **Clean meshes.** Watertight output, so the slicer doesn't need to "repair" anything. STL and STEP export too.
- **Runs anywhere.** One Docker container: editor and MCP on one port, token auth, signed download links.
- **Claude Code plugin** with a design skill. Installs in two commands.

---

## Quick start (Docker)

```bash
git clone https://github.com/allard-code/cadstudio.git && cd cadstudio
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # put this in .env as CADSTUDIO_TOKEN
docker compose up -d --build
```

Open `http://<host>:8765` and sign in with the token.

**Without building yourself:** use the prebuilt image `ghcr.io/allard-code/cadstudio:latest`. Replace `build: .` with `image: ...` in `docker-compose.yml`; this also works as a Portainer stack.

| Variable | Default | Purpose |
|---|---|---|
| `CADSTUDIO_TOKEN` | – (required in compose) | access to the editor **and** `/mcp` |
| `CADSTUDIO_PUBLIC_URL` | `http://localhost:8765` | base URL used in download links returned to Claude |
| `CADSTUDIO_PORT` | `8765` | port inside the container |
| `PUID` / `PGID` | `1000` | owner of the files in `data/` |

Data lives in `./data` (`/data` in the container):

```
data/projects/<project>/project.json   the design: parameters + code per part
data/projects/<project>/exports/       3MF / STL / STEP
data/projects/<project>/meshes/        imported reference models
data/inbox/                            drop STL/3MF files here to import them
```

## Connect Claude

### Claude Code – plugin (recommended)

```
/plugin marketplace add allard-code/cadstudio
/plugin install cad-studio@cadstudio
```

Claude Code asks for your server URL (e.g. `http://192.168.1.50:8765`) and the token, and stores the token securely. The plugin adds the MCP connection and the `cad-design` skill.

### Claude Code – single command

```bash
claude mcp add --transport http --scope user cad-studio http://192.168.1.50:8765/mcp \
  --header "Authorization: Bearer <TOKEN>"
```

### claude.ai and the Claude mobile app

Claude connects to custom connectors from Anthropic's cloud, so the server must be reachable over **public HTTPS**. Two ways to set that up:

- a Cloudflare Tunnel;
- a reverse proxy with your own domain.

Then go to *Settings → Connectors → Add custom connector* and enter `https://cad.example.com/mcp`.

- If your account has **Request headers** (beta), add `authorization: Bearer <TOKEN>` or `x-api-key: <TOKEN>`.
- Otherwise use `https://cad.example.com/mcp?token=<TOKEN>`. Note that the token then appears in URLs and possibly in proxy logs, so use a long token.

### Claude Desktop (local, no Docker)

```bash
python -m venv .venv && .venv/bin/pip install -e .        # Windows: .venv\Scripts\pip
```

Add this to `claude_desktop_config.json` (see `claude_desktop_config.example.json`):

```json
{ "mcpServers": { "cad-studio": { "command": "/path/to/.venv/bin/python", "args": ["-m", "cadstudio", "mcp"] } } }
```

In stdio mode the editor starts automatically on `http://127.0.0.1:8765`.

## Using it

Example prompts:

- *"Make an 80×50×30 mm tray with 2 mm walls, rounded corners and my name as a red inlay on the front. Export as 3MF."*
- *"Import wagon.3mf from the inbox as a reference and design cargo that fits inside with 0.3 mm clearance."*
- *"Make the walls 1.6 mm and the text bigger, then show me a preview."*

**MCP tools:**

| Group | Tools |
|---|---|
| Projects | `list_projects`, `new_project`, `open_project`, `get_project`, `set_notes` |
| Modelling | `set_params`, `set_part`, `update_part`, `add_primitive`, `delete_part` |
| Build plates | `add_plate`, `remove_plate`, `arrange_plates` (and `plate` on `set_part` / `update_part`) |
| Inspecting | `measure`, `render_preview`, `check_floating`, `check_wall_thickness`, `check_bridges` |
| Print preparation | `suggest_orientation` (best side down, optionally for a load direction), `set_print_settings` (profile + overrides, written into the 3MF) |
| Assembly | `set_assembly_item`, `delete_assembly_item`, `render_assembly`, `export_assembly_png`, `check_assembly_fit` |
| Import | `list_inbox`, `import_mesh` (inbox file or URL) |
| Export | `export_3mf`, `export_stl`, `export_step` (each with a download link) |
| Printing | `slice_plate` (G-code with the bundled OrcaSlicer), `send_to_printer` (hand it to Home Assistant) |
| Help | `get_build123d_reference`, `open_editor` |

**Editor:**

- Orbit, pan and zoom the view; click a part to select it.
- Keyboard shortcuts:

  | Key | Action |
  |---|---|
  | **G** | move the selected part with arrows |
  | **X** | X-ray view |
  | **E** | show edges |
  | **F** | fit to view |
  | **1**–**9** / **0** | show bed 1–9 / all beds |
  | **Ctrl+Enter** | build the code |

- The UI is in English and Dutch; switch with the EN/NL selector.

### Build plates

Parts that don't fit on one bed together (say the two halves of a spool) go on separate build plates. The bed bar
under the 3D view switches between beds; *Arrange* spreads all printable parts over as many beds as needed. A
part's position is relative to the centre of its own bed. *Export 3MF* puts every bed in one file as separate
slicer plates (Orca flavour), or, with "1 file per bed", writes one 3MF per bed — use that for PrusaSlicer, which
has no plates.

### Print helpers

Every part's code can use ready-made helpers for functional prints, without importing: `spur_gear` and
`gear_centre_distance`, `d_hole` / `d_shaft`, `teardrop` (horizontal holes without support), `pin` / `pin_hole`,
`screw_boss`, `magnet_pocket` (a cavity to enclose a magnet during a print pause) and `tolerance_coupon` (a small
test strip with engraved clearances: print it once and use the clearance that fits best).

### Assembly view

Show how the printed parts go together. The easiest way for printed parts: next to `result` (how the part lies
on the bed), the part's code also sets `assembled` (where it sits in the finished model), e.g.
`assembled = Pos(0, 0, 25) * chassis` and `result = Rot(180, 0, 0) * chassis`. Several pieces of one part
go in a dict: `assembled = {"left": ..., "right": ...}`.
 Claude adds assembly items with `set_assembly_item(name, code)`: the same
build123d code as a part, but in the assembled position (a part printed upside down is rotated back, for example),
and also reference objects that are never printed, such as a motor or a piece of rail. Assembly items are never
exported, sliced or arranged.

- `render_assembly` draws it for Claude: `ghost=["body"]` makes a shell see-through, `section="x"|"y"|"z"` cuts it
  open (cut faces red), `explode=1` pulls the items apart. `export_assembly_png` saves the same picture with a
  download link.
- In the editor, the *⚙ Assembly* button below the view shows the assembly instead of the build plates: show /
  see-through per item, an *Explode* slider, the *Section* tool, and *Picture (PNG)* to download the current view.
  `http://…/#assembly` opens the editor straight in this view.
- `check_assembly_fit` measures overlap and clearance between all items, so parts that would jam show up first.

### Print pauses

To enclose a magnet or nut, subtract `magnet_pocket()` below the surface and set `pause_at = [z]` in the part's
code (the top of the cavity, mm above the bed). `slice_plate` then pauses the print before the first layer that
closes the cavity; drop the magnet in and resume.

### Printing via Home Assistant

In the editor, *Slice* in the bed bar slices the shown bed and *Print* sends it.
`send_to_printer(plate=N)` uploads the G-code from `slice_plate` to Home Assistant (`/api/file_upload`) and fires
the event `cadstudio_print_request` with `file_id`, `filename`, `project`, `plate`, `material`, `materials`,
`print_time` and `filament_g`. An automation in Home Assistant decides what happens next — for example: ask on
your phone which ACE/AMS slot to print from, then call the printer integration's print action with
`uploaded_gcode_file: "{{ trigger.event.data.file_id }}"`. See
[docs/home-assistant-print.yaml](docs/home-assistant-print.yaml) for a ready-made automation for the Anycubic Cloud
integration.

Set `CADSTUDIO_HA_URL` (e.g. `http://192.168.1.10:8123`) and `CADSTUDIO_HA_TOKEN` — a long-lived access token
(Profile → Security) of an **admin** user, because file upload is admin-only. `CADSTUDIO_HA_EVENT` changes the
event name.

### Multi-colour

- Every colour is its own part with a `filament` slot (1–4; 5–8 for a second unit).
- For inlays, subtract the colour part from the base part (`result = body - part("label")`) so the volumes don't overlap.
- *Export 3MF → "1 object (multi-colour)"* writes one object with a per-part extruder in `Metadata/model_settings.config`, the same layout Bambu Studio and OrcaSlicer use. If your slicer doesn't pick up the assignment, export *separate objects* or STLs and assign the filaments manually.

## Security

**Part code is Python and runs inside the container.** Anyone who can reach the editor or `/mcp` can run code there, so:

- treat `CADSTUDIO_TOKEN` like a password;
- never expose the server without a token.

The container runs as a non-root user and only writes to `/data`. For remote access, a VPN such as Tailscale is the safest option. See [SECURITY.md](SECURITY.md).

## Limitations

- Not a full replacement for Fusion 360: there are no sketch constraints, timeline or assembly joints. Modelling is code plus parameters, which is exactly what Claude is good at.
- Imported meshes (STL/3MF/OBJ/PLY/GLB) can be moved, measured and exported, and combined with your own geometry
  via `mesh_boolean()` (mesh-level union/subtract/intersect) — but not via the regular build123d `+ - &`
  operators, which need a BRep solid. A `mesh_boolean()` result can't be exported to STEP (no BRep solid), same
  as a plain imported mesh. Imported STEP files don't have this limitation: `import_mesh()` (or the editor's
  Import button) gives a STEP file a real BRep solid, usable in normal `+ - &` booleans and STEP-exportable.
- The Docker image is built for `linux/amd64`.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md), which covers the dev setup, tests, code style and how to add a UI language. Changes are tracked in [CHANGELOG.md](CHANGELOG.md).

## License

CAD-Studio is free software, licensed under the [GNU General Public License v3.0 or later](LICENSE). Bundled and used third-party components and their licenses are listed in [NOTICE](NOTICE).
