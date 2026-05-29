# PAC binaries

PAC has two installable/released binaries:

- `pac-endpoint` — endpoint/workspace wrapper. It runs as a host daemon or as the foreground process in a workspace container.
- `pacctl` — client utility for humans, scripts, IDE integrations, provider sync, dynamic API calls, and workspace/endpoint control through PAC.

The source/update zip does not bundle compiled binaries. GitHub Releases publish direct binary assets per OS/architecture and a `RELEASE_BINARIES.json` manifest. Installation/update logic should download the matching release asset and only build locally as an explicit fallback.

Transitional source directories may remain while behavior is merged:

Removed binary folders: `pac-agent`, `zed-binary`, and `pac-endpoint-runner`. Their active behavior now lives in `pac-endpoint` and `pacctl`.
