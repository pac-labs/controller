# Agent loop provider streaming and phase UI follow-up

This pass completes the remaining work from `1.0.339` without adding another large block to `agent_loop.py`.

## What changed

- Streaming provider responses now emit `model_stream_progress` events when an OpenAI-compatible SSE stream is used.
- The planner can abandon a slow blocking provider request and continue with the fallback plan while recording that the old provider thread may still complete later.
- Late completion of abandoned provider calls is recorded through `model_call_late_completed`.
- The session thought/details modal now renders runtime phases and model streaming progress instead of hiding those events in the raw timeline.

## Important runtime behavior

Python cannot force-kill a blocking `urllib` provider request that is already running in a thread. The safer behavior is therefore:

1. stop waiting at the PAC orchestration level,
2. continue the task with a fallback or explicit failure,
3. emit an event that the old provider call was abandoned,
4. record when that old call later completes or fails.

This avoids the UI appearing dead while staying honest about what can and cannot be cancelled in-process.

## Streaming scope

Streaming is enabled for provider types where PAC already expects OpenAI-compatible local SSE behavior (`lmstudio`, `vllm`). For generic `openai-compatible` providers, streaming is opt-in through `model.extra.stream` to avoid breaking providers that accept `stream: true` but do not return SSE.
