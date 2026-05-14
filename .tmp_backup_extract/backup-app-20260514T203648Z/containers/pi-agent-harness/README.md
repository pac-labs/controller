# pi.dev container

This image isolates the Node-based pi.dev from the Python PAC and runner.

Build locally:

```bash
podman build -t localhost/pi-agent-harness:stage11 containers/pi-agent-harness
```

If the npm package name for the pi.dev differs in your environment, override it:

```bash
podman build \
  --build-arg PI_NPM_PACKAGE=<actual-pi-npm-package> \
  -t localhost/pi-agent-harness:stage11 \
  containers/pi-agent-harness
```

The runner launches this image for `execution_mode=pi_container` jobs and passes the prompt via `PI_AGENT_TASK`.
