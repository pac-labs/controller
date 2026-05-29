"""Code intelligence helpers for PAC agent tools."""

from .scanner import diagnostics, find_references, report, safe_root, search_symbols

from .lsp_features import (
    call_hierarchy as lsp_call_hierarchy,
    definition as lsp_definition,
    document_symbols as lsp_document_symbols,
    hover as lsp_hover,
    references as lsp_references,
    shutdown as lsp_shutdown,
    status as lsp_status,
    type_hierarchy as lsp_type_hierarchy,
)
from .language_servers import (
    blast_radius,
    call_hierarchy,
    language_server_status,
    module_index,
    project_metadata,
    type_hierarchy,
)

__all__ = [
    "blast_radius",
    "call_hierarchy",
    "diagnostics",
    "find_references",
    "language_server_status",
    "lsp_call_hierarchy",
    "lsp_definition",
    "lsp_document_symbols",
    "lsp_hover",
    "lsp_references",
    "lsp_shutdown",
    "lsp_status",
    "lsp_type_hierarchy",
    "module_index",
    "project_metadata",
    "report",
    "safe_root",
    "search_symbols",
    "type_hierarchy",
]
