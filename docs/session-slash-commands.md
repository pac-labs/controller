# PAC session slash commands

PAC sessions support a small lookup table for commands typed directly into the chat composer. This keeps the composer simple: normal text goes to the selected model, while `/...` entries become explicit actions.

The command registry is backend-authoritative. The web UI reads the available slash commands from PAC, and the Python session agent uses the same parser internally.

## Built-in lookup table

| Slash command | Type | Requires endpoint binary | Behavior |
| --- | --- | --- | --- |
| `/command <tool> [args]` | endpoint tool | selected tool | Runs a registered endpoint tool on the session-locked endpoint. Example: `/command rg TODO`. |
| `/rg [args]` | endpoint tool | `rg` | Runs ripgrep in the session workspace. |
| `/fd [args]` | endpoint tool | `fd` | Finds files in the session workspace. |
| `/jq [args]` | endpoint tool | `jq` | Runs jq. |
| `/git [args]` | endpoint tool | `git` | Runs git in the workspace. |
| `/delta [args]` | endpoint tool | `delta` | Renders diffs with delta. |
| `/bat [args]` / `/bad [args]` | endpoint tool | `bat` or `batcat` | Previews files. `/bad` is accepted as a typo alias. |
| `/just [args]` | endpoint tool | `just` | Runs a just recipe. |
| `/compact` | agent skill | none | Requests context compaction for the session. |
| `/subagent <instruction>` | agent skill | none | Creates a scoped pi.dev-backed child session/task using the session model/profile and endpoint lock. |
| `/help` | UI/help | none | Shows the lookup table. |

## Plugin model

Endpoint tools are local binaries. Slash commands are thin plugins/skills that translate chat input into one of these backend actions:

- `metadata.tool_name` + `metadata.args` for endpoint binaries.
- `metadata.context_action=compact` for context compaction.
- `metadata.subagent=true` and `metadata.subagent_instruction` for subagent work.

This means new slash commands do not always need new binaries. They only need binaries when they execute something locally on an endpoint. Agent-only skills can remain controller-side plugins.

## Agent use

The Python session agent can use the same slash-command layer through the internal `slash_command` tool.

Example tool calls:

- `{"type":"tool_call","tool":"slash_command","input":{"command":"/rg TODO src"}}`
- `{"type":"tool_call","tool":"slash_command","input":{"command":"/compact"}}`

This keeps user chat shortcuts and agent-invoked shortcuts aligned instead of maintaining two separate command translation paths.

`/subagent` now creates a real child PAC session and child task, linked back to the parent session/task in metadata and timeline events. The spawned worker stays pi.dev-backed and inherits the locked endpoint when one is present.

## Safety

Sessions stay locked to the endpoint selected at creation. Endpoint tool commands execute only on that endpoint and inside the session workspace.
