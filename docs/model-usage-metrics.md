# PAC model usage metrics

PAC keeps model usage in a separate local SQLite database so token burn can be inspected without bloating the session event log.

Database path:

```text
${PACP_HOME}/metrics.db
```

Table:

```text
model_usage
```

The table stores call metadata only. It does not store prompts or model output text.

Important columns:

- `created_at`
- `session_id`
- `task_id`
- `call_type`
- `model_name`
- `provider_name`
- `provider_type`
- `provider_model`
- `endpoint`
- `prompt_tokens`, `completion_tokens`, `total_tokens`
- `prompt_tokens_estimated`, `completion_tokens_estimated`, `total_tokens_estimated`
- `max_tokens`
- `duration_ms`
- `success`
- `error`
- `metadata`

API endpoints:

```text
GET /v1/model-usage?since_hours=24
GET /v1/sessions/{session_id}/model-usage?since_hours=168
```

The dashboard metrics endpoint also includes a `model_usage` object:

```text
GET /v1/metrics/summary
```

Diagnostics bundles include:

```text
model-usage.json
```

This gives enough data to answer questions like:

- which model burned most estimated tokens
- whether planning, decision, or consult calls are responsible
- whether failures/retries are increasing usage
- whether the model is producing large completions or receiving oversized prompts
- whether a provider is returning real usage or only estimates are available

Limitations in this pass:

- LM Studio streaming does not currently expose provider token usage through PAC, so those rows use estimates.
- The metrics database is local SQLite only. It is ready for a later retention/export layer, but there is no Prometheus/OpenTelemetry exporter yet.
