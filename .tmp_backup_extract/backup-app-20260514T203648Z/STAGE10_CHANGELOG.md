# Stage 10 changelog — Web knowledge + artifacts

## Added

- `web_search` agent tool
  - Uses DuckDuckGo's text/HTML endpoint by default.
  - Returns compact JSON results for small-context agents.
  - Intended to be replaceable later with SearXNG, Brave, Kagi, Tavily, etc.

- `web_fetch` agent tool
  - Fetches a URL and returns cleaned text.
  - Prefers installed text browsers: `lynx`, `links2`, or `w3m`.
  - Falls back to built-in HTML cleanup that removes script/style/noscript/canvas/svg content.
  - Supports `max_chars` so 4k/8k models can fetch partial pages safely.

- Artifact API
  - `GET /v1/artifacts`
  - `GET /v1/artifacts?session_id=...&task_id=...`
  - `PUT /v1/artifacts/{session_id}/{task_id}/{name}`
  - `GET /v1/artifacts/{session_id}/{task_id}/{name}`

- Agent artifact tools
  - `save_artifact`
  - `list_artifacts`

- Runner artifact upload
  - Remote runners now scan workspace `artifacts/` and `pi-agent-artifacts/` after a job.
  - If found, they upload a `runner-<job-id>-artifacts.tar.gz` bundle to the PAC.
  - Jobs may also pass `metadata.artifact_paths` for explicit upload candidates.

## Design notes

- Web access is governed by the permission profile `network` setting.
- `ask-first` pauses before web search/fetch.
- `full-control` bypasses those approvals but still logs every web/tool action.
- This is intentionally text-first, because it keeps context usage small and makes local 4096-token models more useful.
