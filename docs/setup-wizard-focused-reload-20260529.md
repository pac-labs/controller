# Setup wizard focused reload pass — 2026-05-29

## Goal

The setup wizard that opens after a reload should explain what still blocks PAC usage. It should not look like a complete catalog of every configurable option.

## Changes

- Added a focused setup planning module at `pi_agent_platform/web/app/setup_wizard_plan.js`.
- The reload wizard now starts on a `Remaining` overview that lists only current required blockers.
- Wizard steps are filtered to the blockers returned by `setup_status.required_issues` and the prerequisites needed to resolve them.
- The stepper now shows blocker counts next to affected steps.
- The provider step is only inserted as a prerequisite when registering a first model would otherwise have no provider to attach to.
- The connection step no longer forces a public URL change when the only blocker is replacing the default dev bearer token.

## Follow-up work not included

- Backend setup status is still limited to the existing blocker types. A later pass can add richer blocker categories for endpoint onboarding, workspace defaults, provider health, and source credentials.
- The wizard still uses the existing provider/model/controller forms. A later UX pass can reduce each step to only the fields needed for the active blocker.
