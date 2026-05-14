# pacctl

`pacctl` is the lightweight PAC-facing client binary intended for IDE helpers,
containers, and endpoint-side workflows.

Current commands:

- `pacctl config get`
- `pacctl context resolve --name docs-customer-a`
- `pacctl context resolve --path docs/customer-a --secrets`
- `pacctl secret get github/pat --value-only`
- `pacctl variable list`
- `pacctl variable get GIT_AUTHOR_EMAIL --value-only`
- `pacctl ram get profile doc-reader`

Runtime configuration:

- `PAC_URL`: controller base URL
- `PAC_TOKEN`: admin bearer token
- `PAC_RUNNER_ID` and `PAC_RUNNER_KEY`: endpoint-scoped retrieval headers
- `PAC_CA_FILE`: optional controller CA bundle
