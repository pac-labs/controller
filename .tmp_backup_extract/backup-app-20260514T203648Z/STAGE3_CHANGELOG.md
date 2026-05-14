# Stage 3 changelog

Added since Stage 2:

- Built-in Web UI served from `/` and static assets under `/ui`
- Dashboard with health, model/tool/session/approval counts
- Create sessions from the browser
- Session list and session detail view
- Remote command execution from the browser
- Live session event streaming via Server-Sent Events
- Pending approval list with approve/reject buttons
- Browser-editable JSON configuration that writes back to `config/config.yaml`
- Runtime config reload after saving configuration
- Traefik deployment example with HTTP to HTTPS redirect and Let's Encrypt HTTP-01
- Podman-friendly compose example
- Extra deployment notes for TLS and reverse proxy usage

Still intentionally next-stage:

- Authentication and per-user RBAC
- Real LLM agent loop and model provider calls
- Containerized worker isolation instead of local shell runtime
- VS Code chat participant and Zed MCP docs refinement
- OpenClaw/ACP adapter
