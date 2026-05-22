# Directory & Access drag/drop membership editing

Version: 1.0.323

This pass adds Active Directory-style drag/drop membership editing to the Directory & Access console.

## Behavior

Directory objects can now be dragged onto groups to add direct membership.

Supported draggable principal types:

- users
- groups
- service accounts
- endpoints
- providers
- certificate identities

Supported drop targets:

- group nodes in the left directory tree
- group rows in the Groups container object table
- the Members section in a selected group detail panel

Dropping an object onto a group calls:

```text
POST /v1/directory/groups/{group_id}/members
```

with:

```json
{"kind":"user","id":"developer"}
```

The backend remains authoritative for validation. It still prevents invalid principals and group nesting cycles.

## Access model

Drag/drop only changes directory membership.

Credentials still answer:

```text
Who are you?
```

Directory membership and group grants still answer:

```text
What are you allowed to do?
```

No token receives independent permissions from this change.

## UI notes

The drag/drop affordance is intentionally simple:

- draggable objects use a grab cursor
- valid group drop targets are outlined while dragging
- a drop target highlights when an object can be added
- the existing member picker remains available for keyboard and non-pointer workflows

The operation is additive. It does not move the object out of any existing group.
