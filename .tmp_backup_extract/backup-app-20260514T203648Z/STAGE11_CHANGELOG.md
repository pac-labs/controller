# Stage 11 changelog - Pi harness container backend

Stage 11 adds the missing, actually wired Pi harness container execution path.

## Added

- `pi_container` runner execution mode.
- Python runner support for launching a disposable Pi harness container.
- Podman preferred, Docker fallback.
- `containers/pi-agent-harness/` image definition.
- `scripts/build-pi-container.sh` helper.
- Runner capability reporting for the configured Pi container image.
- Web UI execution dropdown now includes `pi container`.
- Runner installer can build/preload the Pi harness image and autostart via systemd.

## Execution flow

```text
Web UI / API
  -> PAC queues runner job with execution_mode=pi_container
  -> Python runner pulls the job
  -> Runner starts container image localhost/pi-agent-harness:stage11
  -> Prompt is passed via PI_AGENT_TASK
  -> Logs stream back to PAC
  -> artifacts/ and pi-agent-artifacts/ are bundled and uploaded
```

## Notes

The exact npm package/binary name for the upstream Pi harness may differ. The container image is intentionally overridable via:

```bash
podman build --build-arg PI_NPM_PACKAGE=<actual-package> -t localhost/pi-agent-harness:stage11 containers/pi-agent-harness
```

The entrypoint tries `pi`, `pi-agent`, and `npx pi-coding-agent`, then falls back to a deterministic workspace summary so the backend path can be tested even before the real Pi package name is finalized.
