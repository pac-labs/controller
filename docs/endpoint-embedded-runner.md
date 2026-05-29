# Endpoint embedded runner feature pack

Source version: 0.2.0

This feature pack makes `pac-endpoint` the single host-side endpoint binary. The command runner remains compiled into the endpoint executable, but can be enabled or disabled by configuration.

## Runtime switch

```sh
PAC_RUNNER_ENABLED=true   # default: register, heartbeat, poll and execute jobs
PAC_RUNNER_ENABLED=false  # register and heartbeat only; do not poll or execute jobs
```

## Reported capabilities

Heartbeats include:

```json
{
  "runner": {
    "available": true,
    "embedded": true,
    "enabled": true,
    "workspace": "/path/to/workspace"
  }
}
```

The command channel metadata also reports whether the embedded runner is available for controller-queued jobs.

## Compatibility

The `pac-endpoint-runner` source folder has been removed. New installs build and install `pac-endpoint` only.
