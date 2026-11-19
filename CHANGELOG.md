# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
