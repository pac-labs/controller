# Directory final hardening pass 7

Version: 1.0.321

This pass closes the remaining Directory & Access gaps after the Pass 6 UI replacement.

## Endpoint and provider principals

Endpoints and model providers are now synchronized into the directory as first-class principals:

- endpoint runners become `kind=endpoint` principals
- model providers become `kind=provider` principals
- direct system-managed grant groups give each endpoint/provider identity scoped access only to itself
- deleting an endpoint or provider disables the matching directory principal and revokes its credentials

This keeps endpoint/provider authentication inside the same directory-backed identity model as users and service accounts.

## Credential-only authentication

The legacy raw `user_tokens` runtime fallback has been removed from authentication paths. User login, admin-created tokens, service-account tokens, endpoint tokens, and provider tokens resolve through `directory_credentials`.

Tokens still do not carry permissions. They only identify a principal. The access resolver answers what that principal can use.

## Certificate credential lookup

Certificate credentials can now authenticate when a deployment forwards a verified client certificate fingerprint through one of these headers:

- `X-PAC-Client-Cert-Fingerprint`
- `X-SSL-Client-Fingerprint`

The fingerprint is normalized and resolved against directory certificate credentials. This is request-auth plumbing for reverse-proxy/mTLS deployments; PAC still expects the proxy/TLS layer to verify the client certificate before forwarding the header.

## Endpoint onboarding tokens

Endpoint onboarding now mints a temporary directory service-account credential instead of writing to the old raw user-token table. The temporary principal is system-managed and receives only the minimum grants needed for endpoint registration and artifact retrieval.

## UI hardening

The Directory & Access UI now uses directory routes for group update/delete, and group grant editing includes common permission presets so normal administration does not require hand-writing every grant string.

## Validation

The pass was validated with:

- Python syntax compilation for the full `pi_agent_platform` package
- JavaScript syntax checks for all `web/app/*.js` modules
- YAML parse check for `config/example.config.yaml`
- API import check with a fresh `PACP_HOME`
- FastAPI `TestClient` smoke test for auth status and directory routes
- Direct smoke test for endpoint/provider principal sync, token lookup, certificate fingerprint lookup, and access resolution
