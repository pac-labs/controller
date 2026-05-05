# Controller local pi.dev endpoint

PAC treats the controller host as the built-in local endpoint named `local-PAC`.

The main pi.dev runtime does not create a second endpoint. It is attached to `local-PAC` and uses the `agent-control` workspace, which points at the PAC controller application/source tree.

## Required state

For the main server, pi.dev is required. The endpoint is considered blocked until the local pi.dev runtime image is available. The endpoint card exposes the install action when the image is missing.

Readiness checks include:

- the local endpoint is online;
- the `agent-control` workspace exists;
- the `main-pi-dev` profile exists;
- the configured model exists;
- the local pi.dev runtime image is available;
- PAC wrapper prerequisites such as Node.js are available when wrapper workloads are enabled.

Terminology reminder: pi, agent, and harness all mean pi.dev. PAC integration code around it should be called PAC wrapper or PAC tooling.
