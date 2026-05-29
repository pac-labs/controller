# PAC Playbooks Status

Version: 1.0.403

## Implemented

- YAML playbook catalog with built-in and user-supplied playbooks.
- Typed parameters with required/default/enum handling.
- Step dependencies, checkpoints, resumable runs, and confirm/review/approve gates.
- Agent tools and API routes for listing, starting, approving, resuming, cancelling, importing, exporting, and inspecting playbook runs.
- Playbooks page with catalog cards, parameter editing, run progress, gate approval, resume, cancel, YAML import/export, and output details.
- Visual playbook builder modal for creating a usable playbook from guided fields and JSON step/parameter rows without starting from a raw YAML file.
- Run cancellation now marks active child tasks with `stop_requested`, `cancel_requested`, and `stop_reason=playbook_cancelled`, so the agent loop stops at the next safe cancellation checkpoint.
- Richer conditional execution:
  - parameter and output checks
  - equals / not_equals / contains
  - present / absent
  - step status checks
  - all / any / not condition groups
- Step output capture and export mapping.
- Created sessions from earlier steps can now be targeted by later playbook agent/sub-agent steps.
- Observe metrics for playbook status counts, active runs, step counts, top playbooks, and terminal run duration.

## Important behavior

The `git-workspace-session` built-in playbook exports the session id created by `pac_create_session` and targets the inspection step at that created coding session. This avoids running the inspection inside the original controller session.

Cancellation is cooperative. PAC now propagates stop metadata to child tasks and the loop checks that metadata before and after model/tool work. A model call or external command already in progress still has to return before PAC can finalize the cancellation cleanly.

## Still useful after live validation

- Hard interrupt support for already-running endpoint jobs and long shell commands.
- Richer condition expressions with typed operators for lists and numbers.
- Playbook templates packaged by plugins.
- Dedicated Playbooks settings for reusable templates, default gates, and allowed tool policies.
