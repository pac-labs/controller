# PAC Directory & Access Pass 1

This pass starts the hard cutover from the legacy flat `User.groups` permission path to a single directory-backed authorization model.

## What changed

- Added `DirectoryMember` and `DirectoryCredential` model foundations.
- Extended `Group` so membership lives on the group as `members`.
- Added `pacadm:admins` as the built-in PAC administrator group.
- Added `core/directory.py` for:
  - nested group membership resolution
  - direct/effective membership explanation
  - cycle detection
  - directory tree payloads
  - migration of legacy `User.groups` values into group membership
- Added `core/access_control.py` for:
  - effective grant resolution
  - centralized resource matching
  - system-admin detection through `pacadm:admins`
  - access explanation payloads
- Changed runtime authorization to use directory-effective groups instead of directly reading `User.groups`.
- Added directory API foundations:
  - `GET /v1/directory/tree`
  - `GET /v1/directory/users/{user_id}/membership`
  - `GET /v1/directory/users/{user_id}/effective-access`
  - `GET /v1/directory/groups/{group_id}/effective-access`
  - `POST /v1/directory/groups/{group_id}/members`
  - `DELETE /v1/directory/groups/{group_id}/members/{kind}/{member_id}`

## Migration behavior

When auth scaffolding runs, PAC imports legacy user group values into directory membership:

```text
User.groups = ["admin", "developer"]
```

becomes:

```text
pacadm:admins
└── user:<username>

developer
└── user:<username>
```

After import, `User.groups` is cleared. It remains as a model field only so existing state files can be read during migration. Runtime permission checks no longer use it.

## Important behavior

- Admin access is represented by membership in `pacadm:admins`.
- Nested group membership is supported for authorization.
- Group cycles are rejected.
- Old `/v1/users` and `/v1/groups` endpoints still exist, but user group updates are translated into directory membership.
- Existing UI can continue to call the old endpoints while the new Directory & Access UI is built in later passes.

## Not included yet

- Full Directory & Access UI replacement.
- Service account creation UI/API.
- Hashed token credential table replacing legacy raw `user_tokens`.
- Certificate principal registration.
- Endpoint/provider identity cutover.
- Removal of the `User.groups` model field from persisted data after the compatibility import window.
