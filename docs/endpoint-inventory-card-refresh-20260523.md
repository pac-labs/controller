# Endpoint inventory card refresh

Version: 1.0.332

The Endpoints inventory page has been refreshed from older runner-style cards into workload cards.

## Design intent

Endpoints should read as current PAC workload targets. The page should answer:

- Is this endpoint reachable?
- What platform does it run?
- Can it execute queued commands?
- Does it have a default workspace?
- Is pi.dev ready?
- Are containers/tools/hardware available?
- Which models or directory identity are connected to it?

## UI changes

- Added a dedicated endpoint card renderer in `web/app/endpoint_cards.js`.
- Added a dedicated endpoint action module in `web/app/endpoint_actions.js`.
- Reduced `web/app/endpoints.js` so it loads endpoint data and delegates card/action rendering.
- Replaced placeholder-like status pills with status badges, capability tiles, summary rows, and hardware strips.
- Kept raw/runtime data behind a `Technical inventory` disclosure.
- Added light theme styling for the new endpoint cards.

## Behavior

Endpoint actions still call the existing APIs. This pass changes presentation and structure only:

- edit endpoint
- command
- install Node.js
- install pi.dev
- update
- maintenance
- dry run
- delete

## Follow-up ideas

- Add filtering by platform, readiness, tool package, and online state.
- Add saved endpoint views such as `Windows`, `GPU`, `Needs setup`, and `Ready for sessions`.
- Add a guided endpoint details modal for deeper inventory inspection.
