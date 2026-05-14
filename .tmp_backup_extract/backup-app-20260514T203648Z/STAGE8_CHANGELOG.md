# Stage 8 changelog - Agent Loop

Stage 8 turns the platform from a remote task runner into a first-pass agent system.

## Added

- Real agent loop for prompt-only tasks.
- OpenAI-compatible / LM Studio / vLLM / Ollama chat completion abstraction.
- JSON tool-call protocol for agent actions.
- Agent tools:
  - `list_files`
  - `read_file`
  - `write_file`
  - `shell`
  - `git_status`
  - `git_diff`
- Permission-aware tool execution.
- Approval pause/resume for shell and file writes.
- `full-control` permission profile.
- Full-control timeline event and warning semantics.
- Context profile lookup for effective model budget.
- Agent transcript stored in task metadata.
- First pass of darker purple sharper-corner UI styling.

## Notes

- The agent loop currently expects the model to return a single JSON object.
- Tool calling is model-agnostic; it does not require native provider tool-call support.
- Full-control bypasses approval prompts but still logs tool calls and results.
- Subagent spawning remains a future extension of the same tool-call protocol.
