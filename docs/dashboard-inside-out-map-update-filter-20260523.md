# Dashboard inside-out map and update filter

PAC v1.0.329 adjusts the dashboard topology and update notification behavior.

## Inside-out connection map

The dashboard connection map now starts from the PAC controller in the center and arranges related objects in rings:

- PAC control
- use layer: profiles, source contexts, workspaces
- runtime layer: models and endpoints
- external / infrastructure layer: providers and outside infrastructure

The canvas remains draggable and private per browser. Existing layered-layout positions use a new local-storage key so the inside-out layout starts cleanly.

## Dashboard ordering

The connection map is now rendered before the Operations overview. The overview remains available as a private dashboard widget, but it no longer occupies the first large slot above the topology.

## Update notification filtering

Notification summaries now ignore stale `update_checked` events when their latest version is not newer than the running PAC version. This prevents an older event from continuing to show the currently-installed version as if it were a new update.

Source/package update detection also treats explicit component versions as authoritative before comparing generated content hashes. If a local and remote component report the same version, the package is not shown as an update just because generated hash metadata differs.
