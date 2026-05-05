# Controller pi.dev bootstrap

PAC treats the controller as the first required pi.dev endpoint. The existing `local-PAC` endpoint is the main server endpoint; PAC must not create a second local controller endpoint.

For the controller pi.dev session to run, three things must be true:

1. A working model/profile is configured.
2. The PAC wrapper binary is installed locally, normally at `~/.pacp/bin/pac-endpoint`.
3. The local pi.dev container image exists, normally `localhost/pi-agent-harness:stage11`.

The controller bootstrap flow now does the following when enabled in Settings:

```text
startup
  -> ensure source library exists
  -> check required host tools
  -> build pac-endpoint for the current OS/architecture when missing
  -> copy the binary into ~/.pacp/bin
  -> build/install the local pi.dev container image when missing
  -> refresh local-PAC endpoint metadata
  -> create/repair the agent-control workspace
  -> create/repair the main controller pi.dev session
```

The wrapper source currently used for the local PAC wrapper is `binaries/pac-endpoint`. The Go source compiles, but a successful compile only proves the PAC wrapper binary can run and communicate with PAC. It does not prove the upstream pi.dev npm/runtime package is available, because that depends on the package name/version and network/container build environment on the user host. The pi.dev container install event must therefore surface full stdout/stderr.

If bootstrap fails, check the Events panel first. The expected useful failure points are:

- no Podman/Docker runtime available;
- binary container build failed;
- wrapper artifact was not copied into `~/.pacp/bin`;
- pi.dev image build failed;
- model/profile is not configured.

Terminology rule: `pi`, `agent`, and `harness` all mean pi.dev. PAC-specific helpers around it are PAC wrappers or PAC tooling.
