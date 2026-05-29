# Directory access-control pass 4

This pass moves runtime authorization checks behind the directory access-control service.

## Core changes

- `core/access_control.py` is now principal-aware.
- Routes can pass the authenticated `CurrentUser` directly to `access.can(...)`, `access.require(...)`, `access.effective_grants(...)`, and `access.explain(...)`.
- Service accounts and future endpoint/provider principals are resolved through directory group membership instead of being treated like anonymous controller access.
- Profile, agent-context, workspace, session, diagnostics, model-usage, endpoint, provider, and config/status checks now route through the access helper layer.

## Direct grants

Access-request approval no longer writes new grants into `User.metadata.resource_grants`.
Instead, it creates a system-managed per-principal directory group named like:

```text
pacusr:user:<principal-id>
```

The group contains the principal as a member and stores the approved grants. This keeps authorization directory-native without resurrecting `User.groups`.

## Compatibility notes

- Old metadata grants are still read as a fallback by `access.effective_grants(...)` so existing installations do not lose access immediately.
- New approvals are directory-group based.
- `User.groups` remains only as migration input/output compatibility. It is not used by the runtime access-control helper.

## Remaining work

- Move endpoint/provider registration to create dedicated directory principals automatically.
- Add the Directory & Access frontend tabs for effective access, credentials, and group membership.
- Remove legacy `/v1/users` and `/v1/groups` once the UI has moved fully to `/v1/directory/*`.
- Add a migration that converts old `User.metadata.resource_grants` into `pacusr:*` direct-grant groups, then remove the fallback reader.
