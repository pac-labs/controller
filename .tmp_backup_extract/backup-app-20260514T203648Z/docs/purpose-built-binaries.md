# Purpose-built PAC binaries

PAC binary source builds can compile the controller/server URL into generated binaries.

The build container accepts:

- `PAC_COMPILED_SERVER_URL` or `PAC_BUILD_SERVER_URL`
- `PAC_COMPILED_CONTROLLER_ID`
- `PAC_COMPILED_UPDATE_CHANNEL`

The controller passes `server.public_url` as `PAC_BUILD_SERVER_URL` when building from the web UI.

Runtime override remains possible through `PAC_URL` for endpoint/agent binaries or `--base-url` for the Zed/MCP binary.

Precedence:

1. explicit runtime override
2. compiled default
3. binary fallback/error
