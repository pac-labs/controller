Agent tool source lives here.

Create one folder per tool, for example:

- `plugins/git-helper/`
- `plugins/release-audit/`
- `plugins/docs-reader/`

The IDE coding session can attach these folders live from the trusted workspace.
If a tool folder matches a configured PAC tool id, the IDE will surface it as
source-attached and make it selectable for coding sessions.
