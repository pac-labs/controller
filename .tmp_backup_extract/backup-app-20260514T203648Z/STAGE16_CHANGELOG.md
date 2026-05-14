# Stage 16 changelog

## Rename

- Renamed the visible product name from **Pi Agent Control Plane** to **PAC - Pi Agent Control**.
- Kept the existing `~/.pacp` home directory and `PACP_HOME` override for compatibility.
- Updated UI title, header, footer, service description, docs, and visible client copy.

## UX

- Added a persistent right-side Events rail below the top tabs.
- Events rail stays visible while moving between Dashboard, Sessions, Runners, Models, Tools, Approvals, and Settings.
- Events are grouped visually by status:
  - running/activity
  - completed/done
  - attention/approval/full-control
  - failed/error
- Added event filters and a visible clear button.
- Session timelines still exist, but the right rail now gives the dashboard a stronger control-room feel.

## API

- Added `GET /v1/events/recent?limit=100` for a global recent event feed.
