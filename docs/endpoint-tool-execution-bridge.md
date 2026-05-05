# Endpoint tool execution bridge

PAC endpoints now expose a named tool execution bridge for agents. The endpoint validates the requested tool against its local discovery data, runs the binary inside the configured workspace, and returns stdout, stderr, and exit code to the controller event/job flow.

Hard-required agent endpoint tools:

- `ripgrep` / `rg`
- `fd`
- `jq`
- `git`
- `delta`
- `bat` / `batcat`
- `just`

A queued endpoint command can use a named tool instead of raw shell by setting job metadata:

```json
{
  "tool_name": "git",
  "args": ["status", "--short"]
}
```

The endpoint executes the tool without a shell and returns the result through the existing runner job response. Raw command execution remains available for compatibility and maintenance actions, but agents should prefer named tools wherever possible.
