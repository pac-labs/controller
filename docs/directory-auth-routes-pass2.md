= PAC Directory Auth Routes - Pass 2
:toc:

PAC version 1.0.316 continues the hard cutover toward one directory-backed identity and access system.

== Scope

This pass converts the public auth/user/group management surface toward `/v1/directory/*` routes while keeping the old `/v1/users` and `/v1/groups` routes as compatibility aliases for the existing UI.

== New directory routes

[source,text]
----
GET    /v1/directory/principals
GET    /v1/directory/principals?kind=user
GET    /v1/directory/principals?kind=group
GET    /v1/directory/principals?kind=service_account
GET    /v1/directory/groups
GET    /v1/directory/tree
POST   /v1/directory/users
POST   /v1/directory/groups
POST   /v1/directory/service-accounts
POST   /v1/directory/groups/{group_id}/members
DELETE /v1/directory/groups/{group_id}/members/{kind}/{member_id}
----

== Principal model

Users and groups are now exposed as directory principals. Service accounts are stored as first-class directory principals and can be assigned to groups through the same group membership system.

Principal kinds currently supported by the model:

[source,text]
----
user
group
service_account
endpoint
provider
certificate_identity
----

Only `service_account` receives a creation endpoint in this pass. Endpoint, provider, and certificate identities are intentionally modeled but not fully wired to their runtime systems yet.

== Membership validation

The directory membership endpoint now validates that a requested member exists before adding it to a group. Group-to-group membership still uses the Pass 1 cycle detection.

== Compatibility routes

The existing routes remain available for the current UI:

[source,text]
----
GET    /v1/users
POST   /v1/users
PUT    /v1/users/{user_id}
DELETE /v1/users/{user_id}
GET    /v1/groups
POST   /v1/groups
PUT    /v1/groups/{group_id}
DELETE /v1/groups/{group_id}
----

These routes continue to write into the directory membership model instead of restoring `User.groups` as an authorization source.

== Remaining work

* Replace the Users admin UI with the Directory & Access UI.
* Add token/certificate credential generation under principals.
* Move endpoint and provider registration to directory principals.
* Replace raw `user_tokens` with hashed directory credentials.
* Remove the old `/v1/users` and `/v1/groups` compatibility routes after the frontend has moved.
