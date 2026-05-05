# Main pi.dev profile and agent control workspace

PAC treats `pi`, `agent`, and `harness` as names for the same runtime: **pi.dev**. PAC-specific binaries or integration helpers should be called PAC wrappers or PAC tooling.

## Main pi.dev profile

The default controller-local pi.dev profile is `main-pi-dev`.

Purpose:

- drive the always-available controller pi.dev session;
- use the configured default model/profile in Settings;
- work against the PAC controller itself as the control workspace;
- expose controller-safe development tools such as shell, git, ripgrep, fd, jq, podman, and artifacts when available.

The profile can exist before a real model is selected. Until a model is chosen, the controller pi.dev session reports that the main profile needs a model in Settings instead of creating a fake session against a missing model.

## Agent control workspace

The default workspace is `agent-control`.

Purpose:

- represent the PAC controller application/source tree itself;
- be local to the controller endpoint;
- be non-ephemeral by default;
- bind to the `main-pi-dev` profile;
- give the built-in pi.dev runtime a stable workspace for controller maintenance, source-library work, and future self-improvement tasks.

This workspace is not a remote endpoint workspace and should not be cleaned up by ephemeral workspace expiry logic.
