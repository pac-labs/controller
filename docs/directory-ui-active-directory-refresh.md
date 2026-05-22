# Directory & Access Active Directory style refresh

Version: 1.0.322

This pass adjusts the Directory & Access admin surface so it behaves more like a lightweight directory console instead of a generic card grid.

## Goals

- Make the left pane feel like a directory tree with containers and nested objects.
- Make selected containers show an object list with directory-style columns: name, type, source, status, and description/id.
- Keep credentials visually and conceptually separate from authorization: credentials identify a principal; directory groups and grants decide access.
- Fix light theme contrast so Directory & Access uses light surfaces instead of dark embedded panels.

## UI changes

- Added directory object icons for containers, users, groups, service accounts, endpoints, providers, certificate identities, and credentials.
- Replaced folder summary cards with an object table that resembles an Active Directory object list.
- Added a path chip such as `PAC Directory › People` in the selected container view.
- Added property-list styling for selected principal overview details.
- Kept nested group display in the tree, but with connector lines and compact rows.
- Added theme-correct CSS overrides for light mode.

## Files

- `pi_agent_platform/web/app/directory_access.js`
- `pi_agent_platform/web/styles/directory-access.css`
- `pi_agent_platform/web/styles/directory-access-light.css`
- `pi_agent_platform/web/styles.css`
