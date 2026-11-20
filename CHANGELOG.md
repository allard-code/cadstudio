# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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

[Unreleased]: https://github.com/allard-code/cadstudio/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/allard-code/cadstudio/releases/tag/v0.3.0
