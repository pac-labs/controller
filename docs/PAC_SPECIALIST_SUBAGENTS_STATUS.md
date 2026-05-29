# PAC Specialist Sub-agents Status

PAC now has first-class specialist sub-agent profiles and a structured chain for larger code-change work.

## Implemented

- `SubAgentProfile` with locked tool sets, turn budgets, read-only/plan-only flags, and preferred model roles.
- Specialist profiles:
  - Explore: read-only discovery, 15 turns.
  - Plan: architecture and implementation planning, 10 turns.
  - Coder: scoped implementation, 30 turns.
  - Verify: adversarial testing and regression checks, 20 turns.
  - General-purpose: balanced assistance, 25 turns.
- Sub-agent sessions carry parent session/task references, root session id, locked tools, endpoint binding, and turn budget metadata.
- Parent sessions receive `subagent_started`, `subagent_completed`, and `subagent_failed` events.
- Completed child summaries are stored on the parent task as importable summaries.
- Slash commands:
  - `/subagent <profile> <instruction>`
  - `/explore <instruction>`
  - `/coder <instruction>`
  - `/verify <instruction>`
  - `/general <instruction>`
  - `/chain <instruction>`
- Agent tools:
  - `spawn_subagent`
  - `run_subagent_chain`
  - `import_subagent_summary`
- Automatic code-change chains for larger implementation/refactor requests.
- The default chain is Explore → Plan → Coder → Verify.
- Per-profile model preference hooks choose planner/verifier/coder models from session metadata, task metadata, or the active agent profile.
- Chain events render as timeline cards with child-session summaries.

## Operational behavior

For a larger code-change request, PAC can route the parent task into the specialist chain:

1. Explore gathers verified paths and evidence.
2. Plan turns that evidence into a file-level implementation plan.
3. Coder applies the scoped changes.
4. Verify inspects diffs and runs safe checks.

The parent task records child summaries in `subagent_chain_summaries` and emits `subagent_chain_completed` with a grouped timeline card.

## Still worth improving

- A dedicated frontend side panel that lists child sessions across the whole parent session, not just timeline cards.
- Rich child-summary import controls in the UI.
- Per-profile model preferences in Settings instead of only metadata/profile fields.
- Configurable chain definitions beyond the built-in code-change chain.
- Explicit child-session cancellation when the parent task is stopped.
