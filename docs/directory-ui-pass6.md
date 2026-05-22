# Directory & Access UI pass 6

Pass 6 replaces the old flat Users settings page with a Directory & Access surface.

## Admin view

The settings page now presents these directory sections:

- People
- Groups
- Service Accounts
- Endpoints
- Providers
- Certificate Identities
- Credentials

Groups own membership. Members can be users, groups, service accounts, endpoint identities, provider identities, or certificate identities. The UI no longer edits comma-separated user group fields.

Credentials are shown as identity-only objects. Generated tokens are displayed once; stored rows show safe metadata only. Tokens and certificates do not carry permissions. Permissions continue to resolve through directory membership and group grants.

## Non-admin view

The personal settings modal is now titled **My Access** and shows:

- My profile
- My groups
- My available profiles
- My workspaces
- My contexts
- My tokens
- My access requests

This makes the directory model useful for platform users without exposing global administration.

## APIs used

- `GET /v1/directory/tree`
- `GET /v1/directory/principals?kind=...`
- `GET /v1/directory/groups`
- `GET /v1/directory/principals/{id}/effective-access`
- `GET /v1/directory/principals/{id}/credentials`
- `POST /v1/directory/principals/{id}/tokens`
- `POST /v1/directory/principals/{id}/certificates`
- `DELETE /v1/directory/credentials/{id}`
- `GET /v1/users/me/access`
