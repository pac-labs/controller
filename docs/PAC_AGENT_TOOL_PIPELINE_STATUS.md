= PAC Agent Tool Pipeline Status
Version: 1.0.393

== Current state

PAC routes agent tool calls through a shared `ToolPipeline` before handler or endpoint-runner execution.
The common guardrail sequence is now centralized:

. argument object validation
. typed input schema validation
. workspace path sanity checks
. plan-mode guardrails
. session capability checks
. permission checks
. approval and command policy checks
. read-only cache lookup
. pluggable pre-hooks
. handler or endpoint-runner execution
. pluggable post-hooks
. large-result artifact storage
. read-only cache writes
. workspace/index invalidation after mutations
. per-stage metrics and local trace spans

The typed schema layer is intentionally lightweight and dependency-free. It validates required fields,
primitive types, ranges, enum values, array item types, and any-of / one-of field groups before tool
handlers run.

== Finalization work completed

=== Endpoint schema versioning and retirement

Endpoint-advertised tools now carry schema metadata in `ToolConfig`:

* `schema_version`
* `schema_source`
* `schema_signature`
* `schema_last_seen_at`
* `schema_stale`

When an endpoint stops advertising a dynamic tool, PAC disables that endpoint-owned tool config and marks it stale instead of leaving a misleading active schema behind.

=== Schema validation UI surface

`tool_pipeline_schema_invalid` events now include a `timeline` card payload. Existing session timeline rendering can show the failed tool, required fields, and the validation problems without needing the user to open raw JSON.

=== Hook extension points

Tools can declare guarded `pre_hooks` and `post_hooks` on `ToolConfig`. These hooks run inside the pipeline around tool execution and emit `tool_pipeline_hook` events. Hook failures stop execution or convert the result into a clear denied observation.

=== Read-only batch execution

Added `batch_tools` for bounded parallel execution of read-only tool calls. It rejects mutating tools, nested batches, and more than eight calls. This gives the loop a safe path for parallel discovery after the model has selected concrete read-only searches or reads.

=== Pipeline metrics in Observe

Each pipeline stage records local metrics and trace spans through the embedded observability store. `/v1/metrics/summary`, `/v1/observability/metrics`, and `/v1/observability/tool-pipeline` expose the summary, and the Observe page now has a Tool pipeline card.

== Remaining follow-up after live validation

=== Handler cleanup

Some handlers still contain duplicate permission or approval checks for defense in depth. After live testing confirms the pipeline behaves correctly for local and endpoint-runner tools, those checks can be removed in small focused passes.

=== Cache policy refinement

The current cache is short-lived and in-memory. A later pass should add path-scoped invalidation keys, artifact-backed values for expensive reads, and package-declared cache policies.

=== Endpoint package policy hardening

The pipeline supports dynamic `permission_class` values such as `cluster_write`, `secrets`, and `dangerous`. Endpoint packages still need to consistently publish those classes in their manifests/schemas.

=== Full model multi-call planning

`batch_tools` gives PAC a safe parallel execution primitive. The prompt and loop can later be improved so models prefer `batch_tools` for broad read-only discovery instead of issuing serial one-tool turns.
