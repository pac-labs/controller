# Dashboard topology, private widgets, and notification summary

PAC v1.0.327 updates the dashboard from a fixed metric board into a private operator surface.

## Connection map

The dashboard now includes a connection map that renders PAC relationships as selectable objects:

- PAC controller
- agent profiles
- models
- providers
- source contexts
- workspaces
- endpoints

The backend endpoint is:

```text
GET /v1/dashboard/topology
```

It returns `nodes`, `edges`, and a small summary. The browser lays these out as a layered map and draws links between connected resources.

Examples of relationships shown:

```text
model -> provider
workspace -> endpoint
source context -> workspace
source context -> endpoint
profile -> model
profile -> workspace
controller -> endpoint
```

Selecting a node opens a detail pane with status, object id, scalar metadata, and incoming/outgoing links.

## Private dashboard widgets

The dashboard uses client-side private widget preferences stored in local storage.

System is mandatory. Other widgets can be toggled from the dashboard `Widgets` menu:

- Operations overview
- Connection map
- Execution health
- Critical components
- Setup and updates
- Event activity
- Recent sessions

The mandatory widget rule is intentional: every user dashboard should always show the system status baseline.

## Notification summary

The top notification rail now begins with actionable notices before the event stream.

Backend endpoint:

```text
GET /v1/notifications/summary
```

It surfaces:

- available PAC or source package updates detected by update checks
- pending approvals
- platform alerts
- setup blockers and warnings
- model/provider optimization issues detected from health data

The bell button shows a badge with the total number of items needing attention. Critical notices use a stronger badge tone.

## Notes

Update availability is based on update-check events and source package checks that have already run. PAC still avoids doing a network update check on every dashboard refresh.
