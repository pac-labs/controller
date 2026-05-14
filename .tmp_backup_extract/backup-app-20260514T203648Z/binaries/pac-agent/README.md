# PAC agent binary

Source version: 0.1.0

This is the PAC agent worker binary source. It registers with the PAC controller as an agent-capable endpoint, receives queued jobs, and executes the job command inside the workspace supplied by the controller.

Runtime configuration:

- `PAC_URL`: controller URL
- `PAC_TOKEN`: bearer token when configured
- `PAC_AGENT_NAME`: display name for this agent
- `PAC_WORKSPACE`: default workspace path
- `PAC_CA_FILE`: optional controller CA file

The binary is built by the Source Library binary build action.
