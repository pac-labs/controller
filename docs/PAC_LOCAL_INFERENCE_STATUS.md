# PAC Local Inference Status

PAC keeps model runtimes outside the controller. Local inference is therefore integrated as a discovered provider capability, not as a controller-hosted model process.

## Implemented in 1.0.404

- LM Studio discovery probes:
  - `http://127.0.0.1:1234/v1/models`
  - `http://localhost:1234/v1/models`
  - `http://host.docker.internal:1234/v1/models`
  - endpoint-host derived candidates on port `1234`
  - optional manually supplied URLs
- LM Studio health checks:
  - server reachability
  - OpenAI-compatible model inventory
  - optional tiny chat-completion check
- Provider registration:
  - registers LM Studio as a `lmstudio` provider
  - marks it as local inference
  - caches discovered models
  - optionally creates PAC model entries from live inventory
- API routes:
  - `GET /v1/local-inference/lmstudio/discover`
  - `POST /v1/local-inference/lmstudio/health`
  - `POST /v1/local-inference/lmstudio/register`
- Agent tools:
  - `local_inference_discover`
  - `local_inference_health`
  - `local_inference_register`
- Providers UI:
  - **Detect LM Studio** button
  - discovery result cards
  - one-click registration from a healthy detected endpoint

## PAC-aligned design

PAC does not run LM Studio itself. LM Studio remains an external local provider. PAC discovers it, registers it, tests it, and exposes its models to sessions through the existing provider/model system.

## Still useful after live validation

- `/model lmstudio:<model>` session command alias.
- A more guided Local Inference wizard inside the Add Provider flow.
- Endpoint-host hardware correlation, when LM Studio runs on a known PAC endpoint.
- Capability probing for JSON mode, tool calling, and vision.
- Separate llama.cpp endpoint/package support for fully managed local inference packages.
