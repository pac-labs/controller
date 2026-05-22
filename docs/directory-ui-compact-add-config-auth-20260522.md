# Directory & Access compact add and config auth placement

Version: 1.0.324

This patch corrects the Directory & Access UI after the Active Directory-style refresh and drag/drop pass.

## Fixes

- Added a shared `formatDate(value)` helper in `web/app/ui_helpers.js` so older and newer directory renderers can safely format timestamps.
- Changed `directory_access.js` to use a local-safe date formatter for principal details.
- Moved the authentication status summary out of the Directory & Access users page and into the **Config** settings panel.

## UI changes

Directory & Access now keeps identity management focused on directory objects:

- People
- Groups
- Service Accounts
- Endpoints
- Providers
- Credentials

The old large always-visible add panels have been replaced with compact add menus:

- `+ Add person`
- `+ Add group`
- `+ Add service account`

The left directory tree also exposes small `+` affordances for People, Groups, and Service Accounts. These open the matching compact add menu without crowding or overlapping the directory console.

## Design rule preserved

Credentials still identify the caller. Permissions still come from directory group membership and effective access resolution.
