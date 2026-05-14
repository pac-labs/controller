# PAC endpoint runner compatibility source

Source version: 0.1.0

The runner engine is now embedded in `binaries/pac-endpoint` and can be enabled or disabled with `PAC_RUNNER_ENABLED`.

This folder is kept as a compatibility source entry so older source-library views or scripts that reference `pac-endpoint-runner` do not break immediately. Prefer building and installing `pac-endpoint` for new endpoints.

Migration:

```sh
PAC_RUNNER_ENABLED=true pac-endpoint
```

Disable execution while keeping endpoint identity and heartbeat active:

```sh
PAC_RUNNER_ENABLED=false pac-endpoint
```
