# Stage 18 changelog

## Endpoint terminology

- UI now calls remote workers **Endpoints** instead of runners.
- Added `/v1/endpoints` aliases while keeping `/v1/runners` for backwards compatibility with existing endpoint services.

## Endpoint versioning and updates

- Endpoints report their PAC endpoint version in heartbeat metadata.
- Endpoint cards show version and update status.
- Added **Update endpoint** action per online remote endpoint.
- Added **Update all online endpoints** action.
- Control plane can build a current PAC package via `/v1/admin/current-package`.
- Endpoint update jobs download that package, backup the endpoint app dir, install the new app files, and mark restart-required.

## Fixes

- Fixed endpoint service CLI argument parsing: `--control-plane` and legacy `--PAC` now both work.
