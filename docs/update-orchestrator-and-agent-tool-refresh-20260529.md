# PAC update orchestrator and agent tool refresh

PAC release updates now have an explicit environment orchestration phase. The source/update zip remains source-only, while GitHub Release assets provide the installable binaries.

## Pipeline contract

On pushes to `main`, `.github/workflows/pac-release.yml` runs the release pipeline in this order:

1. Resolve the PAC release version.
2. Set up Go.
3. Compile the first-class binaries:
   - `pac-endpoint`
   - `pacctl`
4. Validate that binary compilation happened before packaging.
5. Generate `pac-full.zip`, `pac-patch.zip`, package seed, binary manifest, and direct binary assets.
6. Publish the GitHub Release.

The default binary targets include Linux, macOS/OSX, and Windows:

- `linux/amd64`
- `linux/arm64`
- `darwin/amd64` for Intel macOS
- `darwin/arm64` for Apple Silicon macOS
- `windows/amd64`

## Update Center behavior

When the PAC Update Center applies a release, PAC now also runs environment orchestration:

1. Download and parse `RELEASE_BINARIES.json`.
2. Download the matching direct GitHub Release assets for the controller host platform.
3. Verify checksums from the manifest.
4. Install `pac-endpoint` and `pacctl` into the local PAC binary cache.
5. Regenerate PAC/pi.dev tool instructions:
   - `PACP_HOME/agent/tool-instructions/PAC_TOOLS.md`
   - `PACP_HOME/agent/tool-instructions/PAC_TOOLS.json`
6. Refresh local endpoint/tool metadata when called by the controller path.
7. Verify the pi.dev runtime state after update.

The orchestration can also be run manually from Update Center with **Run environment refresh**.

## Tool model refreshed for pi.dev

The refreshed instructions tell the pi.dev/PAC agent to use the two-binary model:

- `pac-endpoint` is the resident endpoint/workspace wrapper.
- `pacctl` is the client/integration tool used to communicate with PAC, providers, endpoints, workspaces, and MCP/editor integrations.

Workspace containers should use:

```bash
pac-endpoint workspace run
```

Interactive/control flows should use PAC-routed commands through `pacctl`, for example:

```bash
pacctl workspace exec <workspace> --stream -- <command>
pacctl provider send --file provider.json
pacctl mcp serve
```

## pi.dev container fix

The pi.dev harness image now copies the full `binaries/pacctl/` source tree into its build stage, not only `main.go`. This is required because `pacctl` is now a multi-file Go program.
