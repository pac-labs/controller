# Events rail UI event persistence

Version: 1.0.336

The Events button must show runtime evidence from both backend events and UI-triggered operations.

Changes:

- UI actions now persist events through `POST /v1/events/ui` instead of only keeping a transient in-memory marker.
- The Events rail renders the latest local UI event immediately, then stores it in the backend for later refreshes.
- The Observe page `Open events` button now calls the shared events rail opener instead of referencing a function scoped inside the rail setup.
- The empty Events state now explains that controller logs and traces live under Observe while UI/backend events are shown in the rail.

This keeps the bell/Events rail useful after actions such as endpoint commands, package checks, source builds, and other UI operations that previously said “Details are in Events” but did not always create a persisted event row.
