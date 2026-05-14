# Configure Zed for PAC

PAC can be used by Zed as a context server.

## Local binary

Build the Zed binary from `binaries/zed-binary`, copy the matching artifact to the machine running Zed, then add it to Zed settings.

```json
{
  "context_servers": {
    "pac": {
      "source": "custom",
      "command": "/path/to/pac-zed-binary",
      "args": ["--base-url", "https://admin.pac.local"],
      "env": {}
    }
  }
}
```

## HTTPS bridge

```json
{
  "context_servers": {
    "pac": {
      "source": "custom",
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://admin.pac.local/mcp", "--insecure"],
      "env": {}
    }
  }
}
```

Use `--insecure` only for local/self-signed controller certificates.

## Connectivity check

The Zed MCP helper is a stdio server. When launched directly from a terminal it prints a short message and exits instead of waiting forever for MCP input.

To verify the configured PAC controller URL before adding it to Zed:

```powershell
pac-zed.exe PAC_URL=https://192.168.0.7:8443 --check
```

The same `PAC_URL=...` assignment syntax is accepted by the endpoint and agent binaries on Windows as a convenience.

## Structured timeline events

PAC v1.0.67 adds `pac_add_timeline_event` to the Zed MCP helper. Use it when Zed or an agent wants to add a readable card to the PAC session timeline without forcing the UI to parse Markdown.

Recommended payload shape:

```json
{
  "session_id": "sess_...",
  "type": "zed_note",
  "message": "Zed context attached",
  "data": {
    "timeline": {
      "format": "pac.timeline.v1",
      "title": "Zed context attached",
      "summary": "The active editor context was attached to the PAC session.",
      "fields": {"source": "Zed", "mode": "MCP"},
      "steps": [{"status": "ok", "label": "Context sent"}]
    }
  }
}
```


## Session composer parity

The PAC session composer is intentionally shaped like the ChatGPT input surface: a single primary prompt field, compact command/model controls next to it, and hidden execution metadata. Coding editor integrations should follow the same pattern: show the human prompt first, expose command/model/endpoint selectors as compact controls, and keep raw JSON/tool metadata behind inspect dialogs instead of inline chat text.
