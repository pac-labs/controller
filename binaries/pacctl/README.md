# pacctl

`pacctl` is the PAC client binary.

It is used by humans, scripts, containers, CI, IDEs, and editor integrations to communicate with the PAC controller. `pacctl` routes endpoint/workspace actions through PAC; it does not directly SSH into machines by default.

Examples:

```sh
pacctl api get /v1/version
pacctl poll endpoints
pacctl provider send --file provider.json
pacctl workspace status python-dev
pacctl workspace exec python-dev -- python --version
pacctl workspace exec python-dev --stream -- python long_running_task.py
```

Near-term consolidation target:

- provider/model sync commands live in `pacctl`;
- dynamic API/catalog commands live in `pacctl`;
- MCP/Zed editor bridge behavior is now exposed by `pacctl mcp serve`.
