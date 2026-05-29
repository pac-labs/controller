= Dashboard Freeform Topology and Notification Checks

Version: 1.0.328

== Summary

The dashboard topology map is now a private freeform canvas instead of a fixed layered diagram.
Users can drag topology objects to arrange their own view while PAC keeps the connection lines live.
The layout is stored in the browser and can be reset from the map toolbar.

The notification summary also gained an explicit check action.
It does not force network update checks on every dashboard refresh, but a user can run a check from the notification panel when they want fresh update data.

== Topology behavior

- Nodes are rendered as draggable objects.
- Dragging updates the connection lines while moving.
- Dropped positions are stored in local browser storage.
- The reset button clears the stored layout and returns to the generated layered arrangement.
- Selecting an object still shows its details and connections in the detail panel.

== Notification behavior

- The notification panel still shows cached/recent update, approval, alert, setup, and optimization notices.
- The new `Check now` action calls the PAC application update check and source package update check, then refreshes the summary.
- Failed update checks are tolerated so the notification panel remains usable when an upstream endpoint is unavailable.
