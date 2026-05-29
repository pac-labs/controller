# UI Guided Create Design Rule

PAC creation flows must use guided modals instead of large inline forms or ad-hoc add panels.

## Rule

Every mechanism that creates or adds a resource must start from a compact `+` action and open a guided modal.

This applies to users, groups, service accounts, credentials, endpoints, providers, workspaces, profiles, contexts, secrets, proxy routes, certificates, tools, plugins, and future resource types.

## Required behavior

A create modal should:

1. Explain what is being created.
2. Collect only the fields needed for that resource type.
3. Make follow-up actions clear, such as assigning group membership or generating credentials.
4. Validate required fields before sending the request.
5. Show the created result or an actionable error.
6. Keep authorization semantics clear: credentials identify the principal; directory membership decides access.

## Avoid

- Large always-visible add forms.
- Inline panels that overlap or push important directory data off screen.
- Creating resources from comma-separated text fields when a picker or guided flow can be used.
- Giving tokens or certificates their own permissions.

## Directory & Access implementation

The Directory & Access page now follows this rule for:

- Person creation
- Group creation
- Service account creation

The left-tree `+` buttons and top create buttons open the same guided modal. Membership is still managed from group details or by drag/drop so creation and authorization stay separate.


## Current implementation coverage

As of v1.0.326, the rule is implemented for:

- Directory people, groups, and service accounts.
- Directory token generation and certificate registration.
- Group access grants through guided grant rows instead of raw comma-separated grant text.
- Proxy Route creation and editing.

Sessions, profiles, providers, endpoints, and models already use modal or wizard-style flows and remain aligned with the rule.
