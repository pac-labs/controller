# Agent loop intent recovery and stall visibility — 2026-05-23

This pass addresses two agent-loop failure modes:

1. Startup and step latency could be hard to diagnose because the loop only emitted high-level thinking/model/tool events.
2. Some models returned natural-language intent such as “I will do this” instead of a structured `tool_call`, leaving PAC to ask the model again instead of starting safe workspace work.

## Changes

- Added `core/agent_loop_timing.py` for coarse phase timing around prompt preparation, planning, decision-model calls, compaction checks, and tool execution.
- Slow phases emit `agent_phase_slow` with `phase`, `elapsed_ms`, and relevant model/tool data, so the Events rail can show whether time is spent indexing, planning, model inference, compaction, or tool execution.
- Added `core/workspace_index_cache.py`, a short-lived workspace index cache used by prompt construction. This avoids repeating the expensive project scan when sessions rapidly start new tasks in the same workspace.
- Fixed intent recovery to use `session.tools` instead of the non-existent `session.allowed_tools` attribute.
- Expanded action narration recovery so generic replies like “I will do this” can start a safe `workspace_manifest` scan when the user request itself is clearly investigative or code/workspace related.

## Expected behavior

When the model responds with an intent rather than a valid tool call, PAC should now convert obvious workspace/action intent into the safest read-only first step instead of only asking the model to reformat itself. If a phase still takes too long, the event stream should identify the slow area directly.

## Work not done

- No streaming token-level progress was added for provider calls; slow model inference is now reported after the call returns.
- The workspace index cache is intentionally short-lived and conservative; a deeper incremental indexer can be added later if workspace scans remain expensive on very large trees.
