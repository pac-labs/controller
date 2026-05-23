# PAC Component Atlas

The dashboard topology widget is now the PAC Component Atlas. It is intended to show PAC as a living system rather than a flat list of configuration links.

## Purpose

The atlas places the PAC Controller in the middle of the system view and shows the infrastructure groups that make PAC work:

- PAC Controller internals: Web UI, API, event stream, state store, agent loop, security, observability.
- Agents: PAC Agent and pi.dev Agent with their planning, routing, context, intent, runtime, execution bridge, shell/tool, artifact, and workspace responsibilities.
- Providers and models, including model capability subnodes where the configuration exposes capabilities.
- Endpoints and endpoint runtime metadata, including agent runtime and pi.dev daemon nodes when reported.
- Workspaces and source contexts.
- Sessions, profiles, tools, tool packages, plugins, observability signals, and session artifacts.

## Dashboard behavior

The atlas has three detail levels:

- Overview: compact object-level system overview.
- Infrastructure: shows important registered objects and selected subcomponents.
- Full: shows all emitted nodes, including subcomponents and generated session artifact nodes.

The zoom slider scales the entire atlas. Auto detail mode increases the visible detail as the atlas zooms in.

## Active state

Nodes with active/running/queued/approval-required statuses use the PAC loader icon so active work is visually consistent with the rest of the UI loading and progress behavior.

## Current limitations

This is the first atlas pass. It uses a deterministic grouped layout instead of graph physics or drag persistence. That keeps the layout predictable and makes later refinements easier. Future passes can add panning helpers, group filters, node search, remembered focus, and endpoint-deep inventory once the endpoint metadata is richer.
