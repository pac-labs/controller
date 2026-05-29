# Agent loop timeout and endpoint event noise follow-up

Version: 1.0.341

## Why this pass exists

After 1.0.340 the agent timeline showed the new phase/progress events, but a real run still ended with:

```text
Model call failed: {'error': 'timed out'}
```

The events panel also showed repeated `runner_status_changed` rows for the same endpoint every heartbeat, even though the endpoint remained online.

## Changes

### Provider timeout recovery

OpenAI-compatible local providers can take long enough that a non-streaming request hits the provider HTTP timeout before a full response is returned. PAC now retries timed-out non-streaming OpenAI-compatible, LM Studio, and vLLM chat calls once with streaming enabled when the model allows streaming.

This keeps the user-visible timeline active through `model_stream_progress` events and gives local models a better chance to complete instead of failing the task after one blocking request timeout.

Streaming reads now use a longer inactivity timeout so a slow first token has more room, while still failing if the server stops responding entirely.

### Endpoint heartbeat event de-noising

Endpoint heartbeats often include high-churn probe data, counters, timestamps, or runtime details. Those values should update endpoint cards, but they should not create a global "status changed" event every few seconds.

Heartbeat event emission now separates:

- `runner_status_changed` for real status, labels, or version changes.
- `runner_capabilities_changed` for meaningful capability signature changes, throttled to avoid event spam.

Volatile keys such as timestamps, uptime, pid, memory, and CPU values are removed before comparing capability signatures.

## Files added

- `pi_agent_platform/api/routes/endpoint_heartbeat_events.py`

## Files updated

- `pi_agent_platform/core/providers.py`
- `pi_agent_platform/api/routes/endpoints.py`
- `PAC_CHANGELOG.json`
- `VERSION`
- `VERSION_CURRENT.md`
