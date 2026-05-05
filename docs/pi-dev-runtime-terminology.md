# PAC pi.dev runtime terminology

PAC uses one runtime language for execution:

- `pi`
- `agent`
- `harness`

All three mean the same runtime system: `pi.dev`.

PAC-specific software that integrates with, supervises, packages, or connects to pi.dev should not be named as another harness or agent. Use these names instead:

- PAC wrapper
- PAC controller wrapper
- PAC endpoint wrapper
- PAC tooling

## Controller runtime

The PAC controller has a local pi.dev deployment. It is represented as the controller endpoint and keeps one configurable managed session active when enabled.

Default behavior:

- workspace: PAC controller platform workspace
- profile: selected in Settings
- model: selected directly or inherited from the profile
- runtime: `pi.dev`
- wrapper: PAC controller wrapper

## Endpoint runtime

Endpoints can also run pi.dev. The endpoint-side PAC wrapper reports capabilities, local tools, workspace support, container runtime state, and update status back to the controller.

## Rule for future builds

Do not introduce separate meanings for pi, agent, or harness. Add PAC wrapper/tooling around pi.dev instead.
