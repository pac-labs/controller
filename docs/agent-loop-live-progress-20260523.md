= Agent Loop Live Progress and Fast Planning Timeout
Date: 2026-05-23
Version: 1.0.339

== Purpose

This pass continues the agent-loop responsiveness work from 1.0.338.
The goal is to make slow runs visible while they are still slow, and to prevent the planning pass from blocking the real execution loop for too long.

== Changes

* Added live `agent_phase_started`, `agent_phase_running`, and `agent_phase_completed` events around async agent-loop phases.
* Kept `agent_phase_slow` as the durable stall marker, but now the UI can also show which phase is currently active before the call returns.
* Added a planning fast-path timeout. If the planner model takes too long, PAC emits `agent_plan_timeout`, uses the existing fallback plan, and continues into the decision/execution loop.
* Improved action narration recovery for natural-language search/list intents:
  ** "I will search for X" can become a `ripgrep` tool call when available.
  ** "I will list files" can become a safe workspace/listing step.
* Hardened action narration recovery when a session has no explicit tool list by falling back to configured tool names instead of reading a non-existent config object.

== Behavior

The planner remains useful for normal runs, but it should no longer make the user think the agent is stuck before any actual action starts. The execution timeline should now identify whether PAC is preparing context, waiting for the planner, waiting for the decision model, compacting context, or running a tool.

== Work Not Done

* Provider-level token streaming is still not wired into the timeline; heartbeat events show phase ownership, not partial model tokens.
* A timed-out planning model call may still finish inside its provider thread later because Python cannot forcibly cancel a blocking provider call running in `asyncio.to_thread`.
* The UI can consume the new phase events, but this pass does not add a dedicated progress renderer beyond the existing events/timeline surfaces.
