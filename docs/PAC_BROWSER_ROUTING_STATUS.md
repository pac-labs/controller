= PAC Browser Routing Status

PAC now keeps the browser URL aligned with the active shell page.

Implemented in 1.0.414:

- Main shell navigation updates the browser URL with History API paths such as `/ui/sessions`, `/ui/playbooks`, `/ui/providers`, and `/ui/updates`.
- Browser back/forward navigation reactivates the matching PAC shell page.
- Refreshing a known page route returns the PAC web UI instead of falling back to the main dashboard or a static 404.
- Unknown static assets are still served by the normal `/ui` static mount; only known page slugs are registered as application routes.
- The last selected route is still kept in local storage as a fallback when opening `/ui`.

Still useful after live validation:

- Deep-link selected resources, for example `/ui/sessions/<session-id>` and `/ui/workspaces/<workspace-id>`.
- Add query parameters for secondary panels such as selected settings subpanels or source files.
- Show copied route links in page mastheads or resource detail panels.
