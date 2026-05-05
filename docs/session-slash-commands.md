# PAC session slash commands

PAC sessions support a small lookup table for commands typed directly into the chat composer. This keeps the composer simple: normal text goes to the selected model, while `/...` entries become explicit actions.

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
| `/subagent <instruction>` | agent skill | none | Creates a scoped subagent-style task using the session model/profile. |
| `/help` | UI/help | none | Shows the lookup table. |

## Plugin model

Endpoint tools are local binaries. Slash commands are thin plugins/skills that translate chat input into one of these backend actions:

- `metadata.tool_name` + `metadata.args` for endpoint binaries.
- `metadata.context_action=compact` for context compaction.
- `metadata.subagent=true` and `metadata.subagent_instruction` for subagent work.

This means new slash commands do not always need new binaries. They only need binaries when they execute something locally on an endpoint. Agent-only skills can remain controller-side plugins.

## Safety

Sessions stay locked to the endpoint selected at creation. Endpoint tool commands execute only on that endpoint and inside the session workspace.
