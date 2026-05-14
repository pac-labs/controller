# Stage 2 changelog

Added since the first starter zip:

- SQLite persistence for sessions, tasks and events
- Session/task listing endpoints
- Background command execution with optional `?wait=true`
- Live stdout/stderr events
- Approval and rejection flow
- Workspace file list/read/write API
- Path traversal protection for workspace file operations
- Git status endpoint
- Expanded MCP bridge tools
- Updated model/tool config examples
- Updated README and smoke test

Still intentionally not implemented yet:

- Real LLM agent loop
- Containerized worker isolation
- Authentication/TLS
- Full VS Code chat participant implementation
- ACP/OpenClaw adapter
