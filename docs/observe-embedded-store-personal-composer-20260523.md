# Observe embedded store, My Access modal, and composer de-duplication

Version: 1.0.335

## Summary

This pass adds the next lightweight observability layer under the existing **Observe** menu and fixes two usability issues:

- the personal **My Access** modal was too small to comfortably edit profile, tokens, access, and RAM together;
- the session composer could repeat the same context marker and footer information.

## Embedded observability store

PAC now has a local SQLite observability store at:

```text
${PACP_HOME}/observability.db
```

The store is intentionally small and dependency-free. It complements rotating logs and model usage metrics without embedding a full Victoria stack.

It contains:

- `metric_samples` for lightweight raw samples;
- `metric_rollups_1m` for one-minute rollups;
- `trace_spans` for lightweight spans.

The first producer is API request instrumentation. Static UI/assets are skipped to avoid unnecessary write amplification.

## APIs

New endpoints:

```text
GET  /v1/observability/metrics
GET  /v1/observability/traces
POST /v1/observability/prune
```

`/v1/system/observability` now also reports the embedded store path, size, sample/span counts, and retention settings.

## Observe UI

The Observe page now includes:

- embedded metrics summary;
- recent traces;
- store pruning action.

This keeps runtime evidence under Observe, not Config.

## My Access modal

The personal profile modal is now a larger workspace-style modal:

- wider max width;
- taller scrollable modal body;
- improved two-column layout on desktop;
- larger personal RAM editor;
- responsive single-column layout on smaller screens.

## Composer de-duplication

The composer now avoids repeating attached context markers by:

- de-duplicating attachment chips by kind and label;
- not appending the same prompt context block multiple times;
- simplifying the footer status so it does not repeat details already shown in context/model/endpoint pills.
