# Directory & Access completion pass

Version: 1.0.326

This pass closes the remaining Directory & Access UI cleanup items from the guided creation work.

## Changes

- Added guided credential creation modals for token generation and certificate registration.
- Kept credentials identity-only: they authenticate a principal, while directory group grants decide access.
- Replaced the textual group grant field with a guided grant picker:
  - resource type selector
  - resource id/pattern field
  - action selector
  - common grant presets
  - removable grant rows
- Updated group creation to use the same guided grant picker instead of a free-text grants input.
- Added drag/drop removal for group membership by dropping a direct member onto the selected group's removal zone.
- Converted Proxy Route creation/editing from an inline `<details>` form into a guided modal launched from a compact `+` button.

## Design rule status

The creation rule now applies to the main Directory & Access flows, credential creation, and proxy route creation. Existing major create flows for sessions, profiles, providers, endpoints, and models already use a modal or wizard-style flow.

## Notes

Drag/drop removal only removes direct membership from the selected group. Inherited membership must be changed on the group where that direct relationship exists.
