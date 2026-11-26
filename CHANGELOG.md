# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.10.1] - 2026-11-26

### Fixed
- Multi-plate projects no longer end up beside the build plate by default in the editor: the export menu now
  defaults to one 3MF per bed. Orca, Bambu Studio and Anycubic Slicer Next import a 3MF without project
  settings as geometry on a single plate, so beds 2+ of an "all beds in one file" export were placed beside the
  bed. That option is still there, now last and labelled with this caveat, and `export_3mf` warns about it.
  The MCP instructions and `export_3mf` description now point to `plate=N` / `split_plates=True`.

## [0.10.0] - 2026-11-25

### Added
- Print pauses in the 3MF: a part's `pause_at` heights are written as pause events on the slicer's layer slider
  (Orca / Bambu / Anycubic Slicer Next: `Metadata/custom_gcode_per_layer.xml` per plate, PrusaSlicer:
  `Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml`), on the first layer above each height for the exported
  layer height. The slicer keeps them when the file is opened as a project. `export_3mf(pauses=False)` leaves
  them out; the response lists them per plate.

### Changed
- `slice_plate` exports its working 3MF without those pause events, so its own G-code pauses are not doubled.

## [0.9.0] - 2026-11-25

### Added
- Print settings in the editor: a *Print settings* panel (left, collapsible, with a one-line summary) for the
  project and a *Print settings (this part)* section in the inspector. Pick a profile, override single values
  (an empty field follows the profile or the slicer default, ✕ removes an override, *Reset* clears all); changes
  made by Claude show up live. REST: `GET /api/print-settings/meta`, `PUT /api/print-settings`.
- `set_print_settings(unset=[...])` removes single overrides.

## [0.8.0] - 2026-11-25

### Added
- `suggest_orientation`: ranks which side of a part (or of all parts on a plate, turned together as one rigid
  group) should face the bed - the current orientation, the six axis directions and the largest flat faces -
  on support area, bed contact, height and, with `load_direction`, strength (printed parts are weakest across
  the layer lines). `apply=<rank>` turns the group about its centre and puts it back on the bed; only the parts'
  location changes, their code stays as it is.
- Print settings that travel with the design: `set_print_settings` stores a profile chosen from what the part is
  for (`functional`, `strong`, `watertight`, `decorative`, `draft`, `fine`, `standard`) plus overrides (layer
  height, walls, top/bottom layers, infill density and pattern, supports and support type, brim), for the whole
  project or per part (walls/infill/shells only, e.g. a strong body with a decorative inlay).
- Exported 3MF files carry these settings as per-object / per-part settings, so Anycubic Slicer Next, OrcaSlicer,
  Bambu Studio (`Metadata/model_settings.config`) and PrusaSlicer (`Slic3r_PE_model.config`) open the file with
  them applied. `export_3mf` reports the settings it wrote.
- `slice_plate` uses the project's print settings, takes `infill_pattern` and `support_type` too, and returns the
  settings it sliced with.

## [0.7.0] - 2026-11-25

### Added
- A part's code can set `assembled = <shape>` (or a dict / list of pieces) next to `result`: the part then
  appears in the assembly by itself, in its assembled position, while it still prints the way `result` lies on
  the bed. One source for both, so the assembly follows every change. Stored assembly entries without code
  override the colour, see-through, visibility and explode direction of these items.
- Print pauses: a part's code can set `pause_at = [z, ...]` and `slice_plate(pauses=[...])` adds more heights;
  the G-code then pauses (the printer profile's pause command, `M601` on the Kobra S1) before the first layer
  above each height - to drop a magnet or nut into a closed cavity.
- Editor print bar next to the beds: *Slice* the shown bed with the built-in OrcaSlicer (print time, filament,
  pauses, and a warning when the project changed since) and *Print* to send it via Home Assistant.
  REST: `GET /api/printing`, `POST /api/slice`, `POST /api/print`.

### Changed
- Slicing and sending to the printer moved to `cadstudio/printing.py`, shared by the MCP tools and the editor.

## [0.6.0] - 2026-11-25

### Added
- `check_assembly_fit`: overlap and clearance between every pair of assembly items that come close; flags parts
  that overlap or sit closer than `min_clearance` (default 0.3 mm, a gap that closes up when printed). Pairs that
  are meant to touch or press go in `allow` (with `*` wildcards).
- `check_bridges`: slices each build plate and reports the longest bridge per part plus bridges and overhangs
  beyond `max_bridge_mm` / `max_overhang_mm` (45-degree slopes count as supported), so a sagging ceiling shows up
  before printing.
- Print helpers available in every part's code without importing: `spur_gear`, `gear_centre_distance`, `d_hole`,
  `d_shaft`, `teardrop`, `pin`, `pin_hole`, `screw_boss`, `magnet_pocket` and `tolerance_coupon` (a test strip with
  engraved clearances to measure what your printer needs). Functions of the same name in your shared code win.

## [0.5.0] - 2026-11-24

### Added
- Assembly view: a project can now describe how its printed parts go together. Assembly items are build123d code
  like parts (shared code, parameters and `part("name")` work) placed in their assembled position, and can also be
  reference objects that are never printed (a motor, a battery, rails). They live outside the build plates: never
  exported, sliced or arranged, and saved in checkpoints.
- MCP tools `set_assembly_item`, `delete_assembly_item`, `render_assembly` (see-through items, a section cut along
  X/Y/Z with red cut faces, an exploded view) and `export_assembly_png` (the same picture as a PNG with a download
  link).
- Editor: an *⚙ Assembly* button below the view switches from the build plates to the assembly, with show /
  see-through per item, an *Explode* slider, the existing *Section* tool, and *Picture (PNG)* to download the view.
  `/#assembly` opens the editor straight in the assembly view. REST: `PUT/DELETE /api/assembly/{name}`,
  `GET /api/assembly/mesh/{name}`, `GET /api/assembly.png`.

## [0.4.1] - 2026-11-24

### Fixed
- Prints sent to an Anycubic printer with an ACE (e.g. via `send_to_printer` and the Home Assistant anycubic_cloud
  integration) were refused with "Cannot load AMS paint info from gcode": OrcaSlicer's G-code lacks the
  per-filament `paint_info` that Anycubic Slicer Next writes. `slice_plate` now appends it (plus the
  "filament used" values as lists) as comments at the end of the G-code for Anycubic printers.

## [0.4.0] - 2026-11-24

### Changed
- Releases are automatic: when `main` gets a new version in `pyproject.toml`, the Docker workflow publishes the
  `:<version>` and `:<major>.<minor>` images and creates the `v<version>` tag and GitHub release (no manual tag push).

### Fixed
- Slicing failed with "orca-slicer-env: Permission denied" when the server runs as a non-root user (PUID): the
  unpacked OrcaSlicer AppImage has owner-only directories (`/opt/orca/libexec` is `drwx------`). The image now
  makes `/opt/orca` readable and executable for everyone.
- The editor could show a stale project until a hard refresh (Ctrl+F5): API responses and the editor page are now
  sent with `Cache-Control: no-store`, and the editor's own JS/CSS with `no-cache` (revalidated on every load).
- Resizing a part in the editor (scale) was silently dropped by the REST API.

### Added
- `send_to_printer(plate)`: hands the G-code of a sliced plate to Home Assistant. It uploads the file to
  `/api/file_upload` and fires `cadstudio_print_request` (file id, project, plate, material, print time, grams),
  so a Home Assistant automation can ask which ACE/AMS slot to use and start the print. Configure with
  `CADSTUDIO_HA_URL` and `CADSTUDIO_HA_TOKEN` (admin user); example automation in `docs/home-assistant-print.yaml`.
- The editor shows the running version at the bottom of the right panel: version number, build commit and
  date, the bundled OrcaSlicer version, and whether a newer build is published (a cached GitHub lookup once
  an hour; turn it off with `CADSTUDIO_UPDATE_CHECK=0`). `/health` and the new `/api/version` report it too.
- `slice_plate()`: slices a build plate to G-code with OrcaSlicer, which is now bundled in the Docker image
  (v2.5.2, command line only). Printer, process and filament settings come from OrcaSlicer's own system profiles
  (default printer: `CADSTUDIO_PRINTER`, "Anycubic Kobra S1 0.4 nozzle"), with overrides for layer height,
  infill, walls, top/bottom layers, supports and brim. `materials` picks a filament preset per slot ("PLA",
  "PETG", ...), `one_filament=True` prints the whole plate from one spool. Returns a download link plus the
  slicer's own print-time and filament estimates. The image grows by about 1 GB (OrcaSlicer and the GTK/WebKit
  libraries it links against).
- `export_3mf` (Python API): `filament_map` renumbers filament slots in the exported file.
- `check_floating()`: slices the exported parts of each build plate into layers (like a slicer) and reports
  "floating regions" - areas that would print in mid-air because nothing is below them, e.g. a chimney cylinder
  that starts inside a hollow body or a sphere tip hanging into a cavity. Attached overhangs and bridges are not
  reported; parts on the same plate support each other. Returns height, size and position per island. The
  workflow instructions and the `cad-design` skill now tell Claude to run it (and `check_wall_thickness`) before
  exporting.
- Build plates (beds). Every part has a `plate` number; a project can have several plates, laid out side by side
  in the same grid as Orca/Bambu/Anycubic Slicer Next. Editor: a bed bar under the viewport ("All beds", "Bed 1",
  "Bed 2", …, ＋ / ✕) to switch the view to one bed (also keys `1`–`9`, `0` = all), a bed selector in the
  inspector, an overfull-bed warning, and "Arrange", which spreads all printable parts over as many beds as
  needed (adding beds automatically; multi-colour assemblies and parts linked with `part()` stay together).
  Claude: `plate` in `set_part`/`update_part`, new `add_plate`, `remove_plate`, `arrange_plates`, and `plate` in
  `render_preview`; `measure` reports per plate.
- Multi-plate 3MF: the Orca flavour writes every plate into one file (objects placed in the slicer's plate grid,
  plus `<plate>` blocks in `Metadata/model_settings.config`). `export_3mf(plate=N)` exports a single plate and
  `split_plates=True` writes one 3MF per plate (also in the editor's export menu).
- Parts can be stretched per axis: a new `scale` field (`[sx, sy, sz]`, about the part's own centre). Usable from the
  editor (new "Resize" toolbar button / `S` shortcut with drag handles, plus exact numeric fields in the inspector)
  and from Claude via `set_part`/`update_part`. Applied before export, so 3MF/STL/STEP all reflect it.
- Project-level shared code: a "Shared code" box in the editor (and `set_common_code` for Claude) runs once before
  every part's own code, in the same namespace. Put a helper function/constant used by several parts here once
  instead of repeating it in each part — cuts down on duplicated code in multi-colour designs.
- `mesh_boolean(a, b, op)`: union/subtract/intersect at the mesh level (via manifold3d), for combining an imported
  mesh with your own geometry — the regular `+ - &` operators need a BRep solid, which an imported mesh doesn't
  have. `mesh_of(name)` returns a part's raw triangles. Closes the "imported meshes can't be used in booleans"
  limitation, for 3MF/STL/preview (not STEP, which needs a BRep solid).
- Editor: a Rotate gizmo (toolbar button / `R`) next to Move/Resize, so rotation (already a `location` field) is
  now editable with the mouse too. Holding Shift while dragging any of the three gizmos snaps to coarse steps
  (10 mm / 15° / 0.1×). Duplicate now offsets the copy so it doesn't land exactly on top of the original, and
  selects it. Undo/redo (`Ctrl+Z` / `Ctrl+Shift+Z`, also toolbar buttons) covers move/resize/rotate/colour/
  filament/visibility/export/code edits.
- `export_3mf` now returns a rough filament-weight/cost estimate per filament slot (solid-model volume ×
  density; configurable `filament_density_g_cm3`, optional `filament_price_eur_kg`). It's an upper bound, since
  it assumes 100% infill.
- Parameter presets: save the current `set_params` values under a name and switch back to them later (e.g. a
  "Large"/"Small" variant of the same design) without retyping every number. A dropdown + save/delete buttons
  next to Parameters in the editor; `save_param_preset`/`apply_param_preset`/`delete_param_preset` for Claude.
- `array_part`: duplicate a part in a grid on the bed (e.g. print N copies of a small part on one plate), with
  sensible default spacing (part size + margin) or explicit `spacing_x`/`spacing_y`. Reports whether the whole
  array still fits the bed. Available to Claude and as `POST /api/parts/{name}/array`.
- Overhang highlighting: downward-facing surfaces steeper than 45° from vertical (that aren't resting on the
  bed) are tinted orange, so you can spot where support material will be needed before slicing. A toolbar
  toggle (`O`) in the live 3D editor, and an `overhangs`/`overhang_angle` option on `render_preview` and
  `/api/preview.png` for Claude's own renders.
- Project checkpoints: save a full snapshot of the project (parameters, every part, shared code, imported
  meshes) under a name, and restore it later if a round of changes doesn't pan out. Different from parameter
  presets, which only save `set_params` values. A "Checkpoints" dropdown + save/restore/delete buttons in the
  editor; `save_checkpoint`/`list_checkpoints`/`restore_checkpoint`/`delete_checkpoint` for Claude, and
  `POST /api/checkpoints` / `POST /api/checkpoints/{name}/restore` / `DELETE /api/checkpoints/{name}`.
- Editor: an interactive Measure tool (toolbar button / `M`). Click two points on a part's surface to see the
  straight-line distance between them (e.g. to sanity-check a hole spacing or wall thickness visually);
  markers and the distance stay on screen until you measure again or press Escape. Frontend-only (raycasting
  against the loaded meshes), no new server API.
- STEP import: `import_mesh()` (same tool, dispatches on the file extension) now gives a `.step`/`.stp` file a
  real BRep solid instead of a mesh-only reference, so it works with `part()` and the normal `+ - &` operators
  and can be exported to STEP again — unlike STL/3MF/OBJ/PLY/GLB imports, which stay mesh-only (`mesh_boolean()`).
  Checkpoints now also snapshot imported STEP files, not just meshes.
- `check_wall_thickness(names, threshold_mm=1.2)`: flags walls thinner than the given threshold by casting a
  ray from each face to the opposite wall, so a design can be checked for printability before exporting.
  Returns, per part, the thinnest spot found and its location. New dependency: `rtree` (ray-cast acceleration
  for `trimesh`).
- `export_3mf` now also returns a rough print-time estimate (`print_time_hours_estimate`, from a configurable
  `print_rate_cm3_per_hour`, default 15), alongside the existing filament weight/cost estimate. Same upper-bound
  caveat: it's volume-based (assumes 100% infill), so it's usually higher than what the slicer itself reports
  once you've actually sliced with your real settings.
- Editor: a Section view (toolbar button / `C`). Cuts the model with a plane along X/Y/Z (slider + flip
  button) so you can see the interior - wall thickness, infill cavities, how an inlay fits - without
  exporting and opening the slicer. Frontend-only (three.js clipping planes), no new server API.
- `array_part_polar`: duplicate a part in a circle (bolt-hole patterns, ventilation grilles, spoke/tooth-like
  shapes), alongside the existing grid `array_part`. Default radius/centre fan copies out around the part's
  own current position; pass an explicit `center` to array around a different point. `rotate_copies` turns
  each copy to face outward with the pattern. Available to Claude and as `POST /api/parts/{name}/array_polar`.
- Mesh import now tries to repair a non-watertight mesh (a small hole or a sliver of bad faces, common in
  downloaded models) before it's used: `fill_holes` + merge + `fix_normals`. Lets `mesh_boolean()` (which
  needs a watertight mesh) and the volume/weight estimate work on models that were previously rejected or
  silently wrong. Best-effort - if repair doesn't fully succeed, `watertight` in the build info still reports
  the real, final state, and a hole that spans a sharp edge of the model can in rare cases be patched with
  the wrong (though still watertight) geometry, since its boundary isn't flat and has more than one valid
  triangulation.

### Fixed
- claude.ai custom connector: `/.well-known/oauth-*` now returns 404 instead of 401, so clients don't assume an OAuth sign-in is required.
- An `Authorization` header with just the token (without `Bearer `) is accepted.

### Changed
- The container stops within a few seconds even when an editor tab is open (open live-update streams no longer block shutdown).
- Docker healthcheck requests (`/health`) are no longer written to the access log.

## [0.3.0] - 2026-11-19

First public release.

### Added
- Licensed under GPL-3.0-or-later.
- English as the project language; the editor UI is available in English and Dutch (EN/NL switch, remembers your choice).
- Test suite (model, export, render, web/auth, MCP over HTTP) and CI on Python 3.11–3.13 with MCP SDK 1.x and 2.x.
- Docker image smoke test in CI; releases create versioned images (`ghcr.io/allard-code/cadstudio:0.3.0`) and a GitHub Release.
- Contributing guide, security policy, issue and pull request templates.

### Fixed
- Importing 3MF files failed in clean installs: `networkx` and `lxml` are now dependencies.

### Changed
- Editor shading uses creased normals: flat faces stay flat, curved faces stay smooth.
- Demo project parts are now called `tray` and `label`.

## [0.2.0] - 2026-11-19

### Added
- Docker image and `docker-compose.yml`; editor and MCP (streamable HTTP on `/mcp`) in one process.
- Token authentication (`CADSTUDIO_TOKEN`) via Bearer header, `x-api-key`, login cookie or `?token=`.
- Signed, expiring download links for exports; inbox folder and `list_inbox` / `import_mesh(url=...)`.
- Claude Code plugin (`/plugin marketplace add allard-code/cadstudio`) with a `cad-design` skill.
- Watertight meshes (vertex welding) and a watertight check in the build info.

## [0.1.0] - 2026-11-19

### Added
- Parametric CAD on build123d with parts, parameters and `part()` references.
- Web editor (three.js) with live updates, parameters, code editor, move gizmo, X-ray and export buttons.
- MCP server (stdio) with tools for modelling, measuring, rendering previews and exporting.
- Multi-colour 3MF export for Orca/Bambu/Anycubic and PrusaSlicer, plus STL and STEP.

[Unreleased]: https://github.com/allard-code/cadstudio/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/allard-code/cadstudio/releases/tag/v0.4.1
[0.4.0]: https://github.com/allard-code/cadstudio/releases/tag/v0.4.0
[0.3.0]: https://github.com/allard-code/cadstudio/releases/tag/v0.3.0
