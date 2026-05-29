# PAC Model Hot-Swap Status

PAC supports mid-session model switching through `/model` and the `slash_command` agent tool.

Implemented in this pass:

- `/model` with no arguments lists configured session models.
- `/model <model>` switches the active model for the session.
- Provider-qualified selectors such as `/model lmstudio:<model-id>` resolve to configured provider models.
- Switches run provider/model availability checks before changing the session.
- Capability warnings are produced for models that are not marked JSON/tool capable.
- A model fallback chain is rebuilt after every switch and stored in session/task metadata.
- The agent-loop fallback resolver now prefers the session fallback chain when a model fails or returns empty output.
- Model switch events are recorded in the timeline with old/new model, requested selector, and fallback chain.
- Specialist sub-agents can use per-role model preferences through `model_role_preferences` and existing subagent model maps.

Still useful after live validation:

- Dedicated model picker UI inside the session header/composer.
- Richer provider health checks before switching, such as a tiny chat probe when requested.
- Explicit per-profile fallback-chain configuration in Settings.
- Provider capability re-sync from live provider metadata instead of static model config only.
