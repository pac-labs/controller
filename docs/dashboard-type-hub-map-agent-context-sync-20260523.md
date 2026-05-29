# Dashboard type-hub topology and agent-context session sync

Version: 1.0.330

## Dashboard topology

The dashboard connection map now uses type-centered clusters instead of one controller-centered radial layout.

Each object type has a type center and its configured/runtime instances are arranged around that center:

- Controller
- Profiles
- Contexts
- Workspaces
- Sessions
- Models
- Endpoints
- Providers

The map keeps real instance-to-instance edges visible. For example:

- sessions connect to their workspace
- sessions connect to their model
- sessions connect to their agent context/profile when present
- workspaces connect to endpoints
- models connect to providers
- contexts connect to workspaces/endpoints

Type center membership lines are intentionally lighter than real relationship lines so the useful operational links stand out.

## Agent-context session synchronization

Agent contexts can have role-specific model settings such as executor, planner, reviewer, and retrieval models.

Previously, when an agent context already had a backing session, saving a new model on the context did not update that session immediately. PAC would return the existing `last_session_id` unchanged.

The backing session is now reconciled when the context is opened or saved:

- `session.model` updates from the context executor model
- role model metadata is updated or removed
- permission profile, profile, context mode, tools, workspace path, and concrete workspace fields are refreshed
- an `agent_context_session_synced` event is emitted when the session changes

This keeps the visible session and the agent-context configuration aligned.
