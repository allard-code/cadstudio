# Contributing to CAD-Studio

Thanks for helping out! Bug reports, ideas, translations and pull requests are all welcome.

## Development setup

```bash
git clone https://github.com/allard-code/cadstudio.git && cd cadstudio
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m cadstudio web                              # editor + MCP on http://127.0.0.1:8765
```

On Linux you may need `libgl1` (OpenCASCADE links against it). Python 3.11–3.13 is supported.

Claude Code users: `CLAUDE.md` describes the code base, and `.mcp.json` connects Claude Code to a running CAD-Studio (`CADSTUDIO_URL`, `CADSTUDIO_TOKEN`).

## Before you open a pull request

```bash
ruff check .        # lint (ruff check --fix . fixes most issues)
pytest -q           # all tests must pass
```

- Keep pull requests focused: one feature or fix per PR.
- Add or update tests for behaviour changes (`tests/`).
- Add a line under **Unreleased** in `CHANGELOG.md` for user-visible changes.
- New source files start with `# SPDX-License-Identifier: GPL-3.0-or-later` (or `//` for JS).
- Code, comments, docs, MCP tool descriptions and server messages are in English.
- If you change MCP tools, keep descriptions short and precise. They are what Claude reads to decide how to use the tool.

## Adding a UI language

All editor text is in `cadstudio/static/i18n.js`.

1. Copy the `en` object, translate the values and add it under a new language code (e.g. `de`).
2. Add the language to `<select id="langSelect">` in `cadstudio/static/index.html`.

Missing keys fall back to English.

## Reporting bugs

Please use the issue template and include:

- how you run CAD-Studio (Docker / pip, version, OS);
- the part code or project that fails (`data/projects/<name>/project.json`);
- for slicer problems: the slicer and its version, and the exported 3MF.

## Security issues

Please **don't** open a public issue. See [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the GPL-3.0-or-later, like the rest of the project.

## Code of conduct

Be kind and constructive. Assume good intent, keep discussions about the work, and respect that everyone here is volunteering their time. Harassment or personal attacks are not tolerated; maintainers may remove such content and block participants.
