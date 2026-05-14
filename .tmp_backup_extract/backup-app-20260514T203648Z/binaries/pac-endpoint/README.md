# PAC endpoint binary

Source version: 0.2.0

This binary turns a machine into a PAC endpoint. It now includes the endpoint runner engine inside the same executable.

The endpoint always registers identity and capabilities. Command execution is controlled by `PAC_RUNNER_ENABLED`:

- `PAC_RUNNER_ENABLED=true` or unset: runner is enabled, jobs are polled and executed in the configured workspace.
- `PAC_RUNNER_ENABLED=false`: runner is present but disabled, so the endpoint reports status/capabilities and does not poll for jobs.

Runtime configuration:

- `PAC_URL`: controller URL, for example `https://192.168.0.7:8443`
- `PAC_TOKEN`: bearer token when configured
- `PAC_ENDPOINT_NAME`: display name for this endpoint
- `PAC_WORKSPACE`: default workspace path for commands
- `PAC_RUNNER_ENABLED`: enable or disable embedded command execution
- `PAC_CA_FILE`: optional controller CA file
- `PAC_CLIENT_CERT` and `PAC_CLIENT_KEY`: optional client certificate pair

Self-update jobs use job metadata with `operation=self_update`, `artifact_url`, and optional `sha256`.


## v0.3.0 tool execution bridge

The endpoint includes a named tool execution bridge for agents. Required tools are `rg`, `fd`, `jq`, `git`, `delta`, `bat`/`batcat`, and `just`. Jobs may set `metadata.tool_name` and `metadata.args` so the endpoint runs that local binary directly and reports stdout, stderr and exit code back to PAC.


## Slash command bridge

PAC sessions can map slash commands to endpoint tool invocations. `/command rg pattern`, `/rg pattern`, `/fd name`, `/jq filter`, `/git status`, `/delta`, `/bat file`, `/bad file` and `/just recipe` are translated to named tool jobs with `metadata.tool_name` and `metadata.args`. The endpoint validates the tool registry and executes the binary in the locked session workspace, then reports stdout, stderr and exit code back to PAC.

`/compact` and `/subagent ...` are controller/agent skills rather than endpoint binaries. They are represented as metadata so the agent profile can compact context or spawn a scoped subagent task without needing extra host tools.
