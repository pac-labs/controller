# Directory Credentials — Pass 3

PAC credentials now belong to directory principals instead of carrying their own authorization rules.

## Principle

A credential answers **who is calling**. Directory groups and grants answer **what that principal can do**.

Credentials do not define permissions. A token, endpoint token, provider token, or certificate only authenticates as its `principal_id`.

## API

```text
GET    /v1/directory/principals/{id}/credentials
POST   /v1/directory/principals/{id}/tokens
POST   /v1/directory/principals/{id}/certificates
DELETE /v1/directory/credentials/{id}
```

The token creation response includes the raw token once. Stored credential records keep only hashed token material or certificate fingerprints.

## Credential types

- `api_token` for user and service account principals
- `endpoint_token` for endpoint principals
- `provider_token` for provider principals
- `certificate` for certificate-based principal authentication metadata

Groups cannot authenticate directly. Add a service account, endpoint, provider, or user principal to a group instead.

## Compatibility notes

The older `/v1/auth/tokens` and `/v1/users/me/tokens` endpoints now write and list directory credentials. Existing legacy `user_tokens` rows are still readable as a fallback so older installations do not lock users out during the transition.

## Remaining work

- Wire endpoint/provider registration flows to create dedicated directory principals automatically.
- Add real mTLS/certificate request authentication at the ASGI/proxy boundary.
- Replace the frontend token UI with principal-scoped Credentials tabs.
- Add credential audit retention views and self-service token controls for non-admin users.
