# PAC session thread scope update — 2026-05-23

This pass addresses the confusing session view where an assistant answer can arrive after a newer user prompt and look like it belongs to the newest message.

## Behavior

The sessions UI now tracks the prompt metadata for each task. When a result or thinking row belongs to an older task but arrives after a newer user prompt, PAC adds a visible scope marker:

```text
Reply to earlier request
<original prompt excerpt>
```

This keeps late answers attached to the request they actually answer without hiding the live order of events.

## Event ordering

`SQLiteStore.get_events()` now uses `created_at` plus SQLite `rowid` as the ordering key. Snapshot and stream-style reads are more stable, and same-timestamp events after the last seen event are no longer skipped.

## Follow-up work

A later pass can add a stricter one-active-task-per-session queue, but that needs a product decision because concurrent prompts may still be useful for advanced users.
