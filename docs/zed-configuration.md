# Zed integration with pacctl

Zed should use `pacctl` as the PAC MCP/context-server binary. The old `zed-binary` source folder has been retired so users do not have to download a separate editor-only binary.

Build or download `pacctl` for the local OS/architecture, then configure Zed to run:

```json
{
  "context_servers": {
    "pac": {
      "command": "/path/to/pacctl",
      "args": ["mcp", "serve"],
      "env": {
        "PAC_URL": "https://pac.example.com",
        "PAC_TOKEN": "..."
      }
    }
  }
}
```

`pacctl mcp serve` connects to PAC over the normal controller API, so it works locally or over the internet as long as `PAC_URL`, trust configuration, and the token are valid.
