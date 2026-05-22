# PAC session diagnostics bundle

PAC can export a sanitized diagnostics bundle for a single session when the agent loop feels inefficient, stalls after routing, repeats a tool, or uses too much model context.

## Web UI

Open a session and click **Diagnostics** in the session header. The browser downloads:

```text
pac-diagnostics-<session-id>.zip
```

## API

Download the zip directly:

```bash
curl -fL \
  -H "Authorization: Bearer $PAC_TOKEN" \
  "$PAC_URL/v1/sessions/<session-id>/diagnostics.zip?include_events=1000&full=false" \
  -o "pac-diagnostics-<session-id>.zip"
```

Fetch JSON instead of a zip:

```bash
curl -fL \
  -H "Authorization: Bearer $PAC_TOKEN" \
  "$PAC_URL/v1/sessions/<session-id>/diagnostics?include_events=1000&full=false" \
  -o diagnostics.json
```

## Helper script

From the PAC source tree:

```bash
PAC_URL=http://127.0.0.1:8000 PAC_TOKEN=<token> \
  python3 scripts/collect-pac-diagnostics.py <session-id>
```

The script writes `pac-diagnostics-<session-id>.zip` in the current directory.

Useful switches:

```bash
python3 scripts/collect-pac-diagnostics.py <session-id> --events 3000
python3 scripts/collect-pac-diagnostics.py <session-id> --full
python3 scripts/collect-pac-diagnostics.py <session-id> --no-workspace-state
```

## Contents

The bundle includes:

- `summary.json`: model call count, estimated response tokens, context estimates, compactions, parse failures, empty responses, routing issues, repeated tools, and recent tool sequence.
- `events.json`: sanitized session timeline events.
- `tasks.json`: sanitized task metadata and recent transcript state.
- `config-redacted.json`: model, provider, context profile, agent profile, and available tool information with secrets redacted.
- `diagnostics.json`: all sections combined.

Obvious tokens, API keys, passwords, cookies, and bearer values are redacted automatically. Review the bundle before posting it publicly.

## Model usage metrics

PAC now writes model-call counters to a local SQLite metrics database at `${PACP_HOME}/metrics.db`.
The diagnostics bundle includes a `model-usage.json` file with the rows relevant to the selected session.

Recorded fields intentionally avoid prompt or completion text. Each row stores:

- session/task identifiers when the call came from an agent session
- call type: `plan`, `decision`, `consult`, or generic `chat`
- logical PAC model, provider name/type, provider model, and endpoint
- provider-reported prompt/completion/total token usage when available
- local prompt/completion/total token estimates when provider usage is unavailable
- max output token request, duration, success/failure, and short error text

Useful endpoints:

- `GET /v1/model-usage?since_hours=24` for controller-wide model usage summary
- `GET /v1/sessions/{session_id}/model-usage?since_hours=168` for one session
- `GET /v1/sessions/{session_id}/diagnostics.zip` for a shareable bundle containing `model-usage.json`

Provider usage support:

- OpenAI-compatible non-streaming responses use `usage.prompt_tokens`, `usage.completion_tokens`, and `usage.total_tokens` when present.
- Ollama responses use `prompt_eval_count` and `eval_count` when present.
- LM Studio streaming and providers that omit usage still get deterministic local estimates.
