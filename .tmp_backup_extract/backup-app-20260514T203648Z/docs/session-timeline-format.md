# PAC session timeline format

PAC v1.0.67 adds structured timeline cards for Sessions.

Agents, endpoint tools and Zed integrations can still send plain text events, but richer output should use a small JSON block in `event.data.timeline`:

```json
{
  "type": "tool_result",
  "message": "Inspected workspace",
  "data": {
    "timeline": {
      "format": "pac.timeline.v1",
      "title": "Workspace inspection",
      "summary": "The agent inspected source files and found two likely follow-up actions.",
      "fields": {
        "workspace": "/srv/pac/workspaces/demo",
        "files": 42,
        "duration": "8s"
      },
      "steps": [
        {"status": "ok", "label": "Scanned files", "detail": "Used rg/fd on the endpoint."},
        {"status": "warn", "label": "Missing test command", "detail": "No justfile target was found."}
      ],
      "code": "rg --files | head"
    }
  }
}
```

Supported card fields:

- `title`: short card heading.
- `summary`: human-readable text. Markdown is not required.
- `fields`: key/value metadata rendered as compact chips.
- `steps`: ordered status rows. Useful statuses: `ok`, `completed`, `warn`, `pending`, `failed`, `error`, `info`.
- `code`, `output`, or `diff`: monospace block.
- `links`: array of `{label, href}`.

## Why not only Markdown?

Markdown is still useful for longer prose, but timelines need predictable structure: status, fields, steps, command output and links. `pac.timeline.v1` gives agents a stable JSON contract that the UI can turn into compact cards.

## Zed relation

The Zed MCP helper exposes `pac_add_timeline_event`. Zed can therefore send structured timeline events directly to the active PAC session, while still using `pac_run_task`, `pac_get_events` and `pac_git_diff` for normal interaction.
