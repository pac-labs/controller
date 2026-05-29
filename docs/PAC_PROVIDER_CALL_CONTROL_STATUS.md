# PAC Provider Call Control Status

Version: 1.0.408

## Purpose

PAC must remain controllable while a provider is streaming or blocked inside a synchronous HTTP call. A user pressing stop should not have to wait for the provider socket or local model server to finish.

## Implemented

- Provider calls now run through a polling wrapper instead of one long await.
- Running tasks can abandon an in-flight provider call when `stop_requested` or `cancel_requested` appears in task metadata.
- Abandoned provider calls continue in the executor thread and emit the existing late-completion event if they eventually finish.
- Decision model calls now have a default wall-clock timeout of 180 seconds unless overridden by task/session metadata.
- Streaming OpenAI-compatible providers have a wall-clock stream budget, independent of socket inactivity timeout.
- Stop during a decision call now completes the task with the normal stop result instead of waiting for the provider stream to end.

## Runtime knobs

Task or session metadata can set:

- `decision_timeout_seconds`
- `model_call_timeout_seconds`

Model metadata can set:

- `stream_timeout_seconds`
- `stream_max_seconds`

## Still useful later

- UI control for per-profile model-call timeout.
- Provider-specific stream watchdog metrics in Observe.
- Hard process isolation for provider calls that can be killed rather than abandoned.
