# Session thought-row final-answer de-duplication

Date: 2026-05-23
Version: 1.0.342

## Problem

The session timeline could show provider-status text as if it were the user-visible answer.
Two cases made the UI confusing:

- `model_response_empty` was treated as a model intermediate because the event name contains `model_response`.
- A final model response could be shown once inside the thought row and then again as the actual assistant reply.

This made the thought row read like a status/error update instead of a concise process summary.

## Change

The session thought row now treats empty model responses as internal diagnostics only. They remain visible from the thought/details modal and session log, but they are not used as the headline message in the chat timeline.

Final actions are summarized as `Prepared a final answer` instead of reusing the final answer text. The actual answer remains the separate assistant reply.

While a run is active, streaming/intermediate updates may still appear in the thought row when there is no better intent summary yet. Once the run is closed, the thought row prefers the final intent/process summary and does not echo the answer body.

## Files

- `pi_agent_platform/core/agent_action_recovery.py`
- `pi_agent_platform/web/app/sessions.js`
