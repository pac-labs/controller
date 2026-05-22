# Directory Cutover Pass 5: Remove Legacy User Group Fields

This pass removes the old `User.groups` authorization field from the runtime model.

## Runtime source of truth

Authorization now uses only directory membership:

- users are principals
- groups own direct members through `Group.members`
- groups may contain users, groups, service accounts, endpoint identities, provider identities, and certificate identities
- effective access is resolved through `core.access_control`

Routes and UI should not inspect or edit a `groups` field on a user object.

## Destructive migration

Startup scaffolding imports old stored user payload fields before rewriting the user row:

1. read raw user JSON from the `users` table
2. convert old `groups` values into `Group.members`
3. convert old `metadata.resource_grants` into a system-managed `pacusr:user:<id>` group
4. rewrite the user through the new `User` model so legacy fields are discarded

The migration is intentionally one-way. The directory model becomes authoritative after import.

## UI behavior

The current Directory admin view no longer edits comma-separated user groups.

Membership changes now happen from the selected group detail panel:

- add a user to a group
- add a group to a group
- remove a direct member from a group

User details show direct and inherited groups as read-only effective directory information.

## Compatibility endpoints

`/v1/users` and `/v1/groups` still exist as route aliases for older screens and scripts, but they no longer expose or mutate `User.groups`.
Use `/v1/directory/groups/{group_id}/members` for membership changes.
