# Security policy

## Threat model – please read

CAD-Studio **executes Python code** that is stored in projects (every part is a build123d script). This is by design. As a consequence:

- Anyone who can use the web editor or the `/mcp` endpoint can run code in the CAD-Studio process.
- Always set `CADSTUDIO_TOKEN` when the server is reachable from anything other than your own machine, and treat the token like a password.
- Prefer a VPN (e.g. Tailscale) over exposing the port to the internet. If you do expose it (e.g. for claude.ai), use HTTPS and a long random token.
- The Docker image runs as an unprivileged user and only writes to `/data`; don't mount sensitive host paths into the container.
- Only open project files from people you trust.

## Supported versions

Security fixes are made for the latest release.

## Reporting a vulnerability

Please report vulnerabilities privately via GitHub's **[Report a vulnerability](https://github.com/allard-code/cadstudio/security/advisories/new)** (Security → Advisories). Don't open a public issue.

Please include the version, how you run CAD-Studio and steps to reproduce. You can expect a first response within a week.
