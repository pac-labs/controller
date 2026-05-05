from __future__ import annotations

"""Small MCP-compatible stdio bridge for PAC - Pi Agent Control.

This intentionally keeps dependencies light. It speaks the JSON-RPC messages used by
MCP clients for initialize, tools/list and tools/call and forwards calls to the HTTP API.
"""

import argparse
import json
import sys
from typing import Any

import httpx


def write(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


class PiClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, json_body: dict[str, Any] | None = None) -> Any:
        with httpx.Client(timeout=300) as client:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
            response = client.request(method, f"{self.base_url}{path}", json=json_body, headers=headers)
            response.raise_for_status()
            return response.json()


def tool_schema() -> list[dict[str, Any]]:
    return [
        {"name": "pi_list_models", "description": "List configured model providers and context windows.", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "pi_list_tools", "description": "List configured tool capabilities and approval patterns.", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "pi_list_profiles", "description": "List agent, permission and workspace profiles.", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "pi_create_session", "description": "Create a remote coding session from a central agent profile and workspace profile, with optional overrides.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "agent_profile": {"type": "string"}, "workspace_profile": {"type": "string"}, "permission_profile": {"type": "string"}, "model": {"type": "string"}, "context_mode": {"type": "string"}, "workspace_path": {"type": "string"}, "git_url": {"type": "string"}, "git_branch": {"type": "string"}, "tools": {"type": "array", "items": {"type": "string"}}}}},
        {"name": "pi_run_command", "description": "Run a shell command in an existing session. Returns immediately unless wait=true.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "command": {"type": "string"}, "prompt": {"type": "string"}, "wait": {"type": "boolean"}}, "required": ["session_id", "command"]}},
        {"name": "pi_approve_task", "description": "Approve a command that matched an approval-required pattern.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "wait": {"type": "boolean"}}, "required": ["task_id"]}},
        {"name": "pi_reject_task", "description": "Reject a task waiting for approval.", "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["task_id"]}},
        {"name": "pi_get_events", "description": "Get recent events for a session.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
        {"name": "pi_list_files", "description": "List workspace files for a session.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "path": {"type": "string"}}, "required": ["session_id"]}},
        {"name": "pi_read_file", "description": "Read a text file from a session workspace.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "path": {"type": "string"}}, "required": ["session_id", "path"]}},
        {"name": "pi_write_file", "description": "Write a text file inside a session workspace.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["session_id", "path", "content"]}},
        {"name": "pi_get_diff", "description": "Get git diff for a session workspace.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
        {"name": "pi_git_status", "description": "Get git status for a session workspace.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}},
    ]


def call_tool(client: PiClient, name: str, args: dict[str, Any]) -> Any:
    if name == "pi_list_models":
        return client.request("GET", "/v1/models")
    if name == "pi_list_tools":
        return client.request("GET", "/v1/tools")
    if name == "pi_list_profiles":
        return client.request("GET", "/v1/profiles")
    if name == "pi_create_session":
        workspace = {"type": "profile", "profile": args.get("workspace_profile")} if args.get("workspace_profile") else {"type": "local", "path": args.get("workspace_path")}
        if args.get("git_url"):
            workspace = {"type": "git", "url": args["git_url"], "branch": args.get("git_branch"), "path": args.get("workspace_path")}
        body = {"name": args.get("name"), "agent_profile": args.get("agent_profile"), "permission_profile": args.get("permission_profile"), "model": args.get("model"), "context_mode": args.get("context_mode"), "tools": args.get("tools", []), "workspace": workspace}
        return client.request("POST", "/v1/sessions", body)
    if name == "pi_run_command":
        body = {"prompt": args.get("prompt") or args["command"], "command": args["command"]}
        suffix = "?wait=true" if args.get("wait") else ""
        return client.request("POST", f"/v1/sessions/{args['session_id']}/tasks{suffix}", body)
    if name == "pi_approve_task":
        suffix = "?wait=true" if args.get("wait") else ""
        return client.request("POST", f"/v1/tasks/{args['task_id']}/approve{suffix}")
    if name == "pi_reject_task":
        reason = args.get("reason", "Rejected by MCP client")
        return client.request("POST", f"/v1/tasks/{args['task_id']}/reject?reason={reason}")
    if name == "pi_get_events":
        return client.request("GET", f"/v1/sessions/{args['session_id']}/events/snapshot")
    if name == "pi_list_files":
        return client.request("GET", f"/v1/sessions/{args['session_id']}/files?path={args.get('path', '.')}")
    if name == "pi_read_file":
        return client.request("GET", f"/v1/sessions/{args['session_id']}/files/content?path={args['path']}")
    if name == "pi_write_file":
        return client.request("PUT", f"/v1/sessions/{args['session_id']}/files/content", {"path": args["path"], "content": args["content"]})
    if name == "pi_get_diff":
        return client.request("GET", f"/v1/sessions/{args['session_id']}/diff")
    if name == "pi_git_status":
        return client.request("GET", f"/v1/sessions/{args['session_id']}/git/status")
    raise ValueError(f"Unknown tool: {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://localhost")
    parser.add_argument("--token", default=None)
    args = parser.parse_args()
    client = PiClient(args.base_url, args.token)

    for line in sys.stdin:
        try:
            req = json.loads(line)
            method = req.get("method")
            req_id = req.get("id")
            params = req.get("params") or {}
            if method == "initialize":
                write({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "pac", "version": "1.0.79"}, "capabilities": {"tools": {}}}})
            elif method == "tools/list":
                write({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tool_schema()}})
            elif method == "tools/call":
                result = call_tool(client, params["name"], params.get("arguments") or {})
                write({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}})
            else:
                write({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}})
        except Exception as exc:  # noqa: BLE001
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": str(exc)}})


if __name__ == "__main__":
    main()
