# Windows endpoint remote execution

PAC endpoints are OS-agnostic execution environments. A Windows endpoint is registered the same way as any other endpoint, but it advertises `windows` as its workload platform and uses PowerShell for host execution by default.

## Behavior

- Windows endpoint binaries are built with the existing `windows/amd64` target.
- The endpoint registers with labels such as `endpoint`, `windows`, and `remote-execution`.
- Heartbeats advertise `os_family=windows`, `remote_code_execution`, and the local command channel.
- Host jobs queued to a Windows endpoint default to PowerShell.
- The endpoint job still runs through the PAC endpoint job queue and workspace boundary.
- Credentials identify the endpoint principal; directory groups/grants decide what it can do.

## Onboarding

Use **Endpoints → Endpoint wizard**, choose `Windows amd64`, generate the install kit, then run the PowerShell command on the Windows host. The command downloads the compiled endpoint binary, sets the temporary onboarding token, and starts the endpoint process.

For persistent operation, wrap the resulting command in a Windows Service or Scheduled Task after validating the endpoint heartbeat.

## Security boundary

This is remote code execution by design, but it is not an unauthenticated shell. Jobs require directory access to the endpoint resource, are queued through the controller, and execute inside the configured endpoint workspace by default.
