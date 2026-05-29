# PAC Code Intelligence Status

Updated for PAC 1.0.400.

## Implemented

PAC now has a cross-language code-intelligence layer available to normal sessions and specialist sub-agents.

Static and tool-driven intelligence:

- `code_intelligence_report` — detects project languages, markers, language-server availability, and static symbols.
- `code_language_servers` — reports language server/compiler/tool availability for Python, TypeScript/JavaScript, Go, Rust, and C#.
- `code_project_metadata` — prepares or runs project metadata commands such as `cargo metadata`, `go list`, package.json summaries, Python marker checks, and dotnet project discovery.
- `code_symbol_search` — searches static symbols.
- `code_definition` — finds likely symbol definitions.
- `code_references` — finds textual references.
- `code_call_hierarchy` — builds a static caller list by combining reference search with function/method ranges.
- `code_type_hierarchy` — extracts inheritance/implementation relationships for Python, TypeScript, Rust, and C#.
- `code_module_index` — builds a language-aware module/file index.
- `code_blast_radius` — estimates affected files, definitions, references, languages, and validation commands for a symbol change.
- `code_diagnostics` — prepares or runs safe diagnostics such as `cargo check --message-format=json`, `python -m compileall`, `go test ./...`, `npx tsc --noEmit`, and `dotnet build --no-restore`.
- `code_roslyn_analysis` — first C# semantic-readiness pass: discovers solutions/projects, extracts C# types/methods/inheritance relationships, checks dotnet availability, and can optionally run `dotnet build --no-restore` for diagnostics.

Persistent JSON-RPC LSP intelligence:

- `code_lsp_status` — reports persistent client state and available language-server commands.
- `code_lsp_document_symbols` — opens a file through the language server and returns document symbols.
- `code_lsp_definition` — resolves go-to-definition from a file/line/character position.
- `code_lsp_references` — resolves references from a file/line/character position.
- `code_lsp_hover` — returns hover/type details from a file/line/character position.
- `code_lsp_call_hierarchy` — requests incoming/outgoing call hierarchy where the server supports it.
- `code_lsp_type_hierarchy` — requests supertype/subtype hierarchy where the server supports it.
- `code_lsp_rename_plan` — requests a language-server rename workspace edit and returns a dry-run diff preview.
- `code_lsp_rename_apply` — applies the same rename edit through file-write permission and ToolPipeline approval.
- `code_lsp_shutdown` — stops persistent language-server clients for a workspace or language.

## Persistent LSP mode

PAC can keep controller-side JSON-RPC language-server processes alive per `(workspace, language)`.
The client performs `initialize`, `initialized`, `textDocument/didOpen`, then feature requests over stdio with LSP framing.

Supported server commands:

- Rust: `rust-analyzer`
- Python: `pyright-langserver --stdio`, fallback `pylsp`
- Go: `gopls`
- TypeScript/JavaScript: `typescript-language-server --stdio`
- C#: `csharp-ls`

If a server is not installed or a language-server feature is unsupported, the LSP tool returns a structured `lsp-error` payload instead of hanging the agent loop.

## Endpoint/container behavior

Coding sessions can run `code_language_servers`, `code_project_metadata`, `code_diagnostics`, `code_lsp_status`, `code_lsp_endpoint_prepare`, and `code_roslyn_analysis` through the endpoint runner when the session is bound to a container-capable endpoint. This allows Rust, Go, TypeScript, Python, and C# checks to run in the same runtime image as the workspace instead of on the controller host.

`code_lsp_endpoint_prepare` writes `.pac/lsp/server-capabilities.json` in the workspace so later model turns can see which language servers and toolchains are actually available inside the endpoint/container image.

The persistent LSP client currently runs controller-side against the materialized controller workspace. Endpoint-side long-lived LSP daemons are still a larger future extension because the current runner job contract is short-lived command execution.

## Timeline/UI behavior

Code-intelligence tool results now emit compact timeline card payloads for:

- LSP server readiness
- document symbols
- definitions/references/hover
- call/type hierarchy
- rename previews and applied rename summaries
- endpoint LSP preparation
- C# semantic-readiness analysis

The raw JSON output remains available in event details, while the visible session timeline shows file, language, changed-file counts, short symbol lists, and rename diffs where relevant.

## Still needed

- Endpoint-side long-lived JSON-RPC LSP proxy/daemon for container-only toolchains.
- Real Roslyn semantic analyzer integration beyond static C# extraction and `csharp-ls`/dotnet readiness.
- Cached symbol databases with ToolPipeline invalidation.
- Dedicated tree/diff UI components for symbols, references, and hierarchy results beyond the generic timeline card renderer.
- Background index refresh for large workspaces.
