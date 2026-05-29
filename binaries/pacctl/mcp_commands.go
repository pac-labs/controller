package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
)

type mcpRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type mcpResponse struct {
	JSONRPC string `json:"jsonrpc"`
	ID      any    `json:"id,omitempty"`
	Result  any    `json:"result,omitempty"`
	Error   any    `json:"error,omitempty"`
}

func handleMCP(ctx context.Context, c *client, args []string) int {
	if len(args) < 2 || args[1] != "serve" {
		usage()
		return 2
	}
	return serveMCP(ctx, c)
}

func serveMCP(ctx context.Context, c *client) int {
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var req mcpRequest
		if err := json.Unmarshal(line, &req); err != nil {
			writeMCP(mcpResponse{JSONRPC: "2.0", Error: map[string]any{"code": -32700, "message": err.Error()}})
			continue
		}
		result, callErr := dispatchMCPTool(ctx, c, req)
		if callErr != nil {
			writeMCP(mcpResponse{JSONRPC: "2.0", ID: req.ID, Error: map[string]any{"code": -32000, "message": callErr.Error()}})
			continue
		}
		if req.ID != nil {
			writeMCP(mcpResponse{JSONRPC: "2.0", ID: req.ID, Result: result})
		}
	}
	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}

func writeMCP(resp mcpResponse) {
	data, _ := json.Marshal(resp)
	fmt.Println(string(data))
}

func dispatchMCPTool(ctx context.Context, c *client, req mcpRequest) (any, error) {
	switch req.Method {
	case "initialize":
		return map[string]any{"protocolVersion": "2024-11-05", "serverInfo": map[string]any{"name": "pacctl", "version": version}, "capabilities": map[string]any{"tools": map[string]any{}}}, nil
	case "tools/list":
		return map[string]any{"tools": []map[string]any{
			{"name": "pac_version", "description": "Get PAC server version.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
			{"name": "pac_list_providers", "description": "List configured PAC providers.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
			{"name": "pac_list_workspaces", "description": "List PAC workspace profiles and online workspace agents.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
		}}, nil
	case "tools/call":
		var payload struct {
			Name      string         `json:"name"`
			Arguments map[string]any `json:"arguments"`
		}
		_ = json.Unmarshal(req.Params, &payload)
		switch payload.Name {
		case "pac_version":
			return c.requestJSON(ctx, "GET", "/v1/version", nil)
		case "pac_list_providers":
			return c.requestJSON(ctx, "GET", "/v1/providers", nil)
		case "pac_list_workspaces":
			return c.requestJSON(ctx, "GET", "/v1/workspaces", nil)
		default:
			return nil, fmt.Errorf("unknown PAC MCP tool: %s", payload.Name)
		}
	default:
		return map[string]any{}, nil
	}
}
