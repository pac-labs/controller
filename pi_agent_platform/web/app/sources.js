// Source library coordinator.
//
// The source/workbench implementation is intentionally split into focused
// modules loaded before this file:
// - source_tree.js handles file tree rendering, tabs, and entry actions.
// - source_downloads.js handles binary artifact browsing and cleanup.
// - source_contexts.js resolves source contexts and stores context metadata.
// - source_ide_context.js maps IDE workspaces/sessions to source browsing.
// - source_tools.js exposes tool-source attachment helpers.
// - source_coding_activity.js manages coding-session prompts and activity.
// - source_secrets_variables.js manages variables, secrets, and PAC RAM.
// - source_marketplace.js renders marketplace search/inspection UI.
// - source_build_actions.js starts binary/container builds.
//
// This thin file is kept so existing script order and external references to
// /ui/app/sources.js remain stable while the implementation is modularized.
