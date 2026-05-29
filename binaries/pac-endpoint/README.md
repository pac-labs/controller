# pac-endpoint

`pac-endpoint` is the PAC endpoint/workspace wrapper.

It is the binary installed where work happens:

- host machines and VMs;
- endpoint containers;
- workspace containers;
- local/controller-adjacent wrappers when needed.

## Modes

```sh
pac-endpoint daemon
```

Default long-running host behavior. It registers the endpoint, sends heartbeat, reports capabilities, polls PAC-routed jobs, executes allowed work, and handles self-update jobs.

```sh
pac-endpoint workspace run
```

Container/workspace foreground behavior. It reads workspace config from JSON/env, registers the workspace with PAC, starts heartbeats, waits for PAC-routed commands, streams command stdout/stderr back to PAC, and keeps the container alive until the container stops.

```sh
pac-endpoint workspace register
```

One-shot registration/debug behavior. It registers or refreshes workspace metadata and exits.

## Workspace config

Default JSON locations:

- `/etc/pac/workspace.json`
- `/pac/workspace.json`
- `workspace.pac.json`

Environment overrides:

- `PAC_URL` or `PAC_CONTROLLER_URL`
- `PAC_TOKEN` or `PAC_WORKSPACE_TOKEN`
- `PAC_WORKSPACE_ID`
- `PAC_WORKSPACE_NAME`
- `PAC_WORKSPACE_ROOT`
- `PAC_WORKSPACE_LIFETIME`
- `PAC_WORKSPACE_LABELS`

The workspace connection is outbound HTTPS, so it works through NAT and over the internet without exposing container ports.
