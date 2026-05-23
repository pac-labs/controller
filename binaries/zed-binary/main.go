package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

var version = "0.1.0"
var defaultServerURL = "https://localhost"
var defaultControllerID = ""
var defaultUpdateChannel = "stable"

type rpcReq struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type rpcResp struct {
	JSONRPC string `json:"jsonrpc"`
	ID      any    `json:"id,omitempty"`
	Result  any    `json:"result,omitempty"`
	Error   any    `json:"error,omitempty"`
}

type client struct {
	base  string
	token string
	http  *http.Client
}

func (c *client) req(method, path string, body any) (any, error) {
	var r io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		r = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.base+path, r)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("PAC HTTP %d: %s", resp.StatusCode, string(data))
	}
	if len(data) == 0 {
		return map[string]any{"ok": true}, nil
	}
	var out any
	if err := json.Unmarshal(data, &out); err != nil {
		return string(data), nil
	}
	return out, nil
}

func write(v any) { b, _ := json.Marshal(v); fmt.Println(string(b)) }

func applyEnvAssignments(args []string) []string {
	kept := make([]string, 0, len(args))
	for _, arg := range args {
		if strings.HasPrefix(arg, "--") || strings.HasPrefix(arg, "-") || !strings.Contains(arg, "=") {
			kept = append(kept, arg)
			continue
		}
		parts := strings.SplitN(arg, "=", 2)
		key := strings.TrimSpace(parts[0])
		value := ""
		if len(parts) == 2 {
			value = strings.TrimSpace(parts[1])
		}
		if key == "" {
			kept = append(kept, arg)
			continue
		}
		// Windows users often run: pac-endpoint.exe PAC_URL=https://host:8443.
		// Treat KEY=value CLI tokens as process env assignments for this run.
		if isSafeEnvAssignmentKey(key) {
			_ = os.Setenv(key, value)
			continue
		}
		kept = append(kept, arg)
	}
	return kept
}

func isSafeEnvAssignmentKey(key string) bool {
	if !strings.HasPrefix(key, "PAC_") {
		return false
	}
	for _, r := range key {
		if (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' {
			continue
		}
		return false
	}
	return true
}

func tools() []map[string]any {
	return []map[string]any{
		{"name": "pac_version", "description": "Get PAC server version.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
		{"name": "pac_list_agent_contexts", "description": "List usable PAC agent contexts for editor sessions.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
		{"name": "pac_list_my_workspaces", "description": "List personal PAC workspaces available to the current user.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
		{"name": "pac_bootstrap_editor_session", "description": "Bootstrap or attach a PAC editor session from an agent context or workspace and pass current editor state.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"origin": map[string]any{"type": "string"}, "context_id": map[string]any{"type": "string"}, "workspace_id": map[string]any{"type": "string"}, "editor": map[string]any{"type": "string"}, "workspace_root": map[string]any{"type": "string"}, "active_file": map[string]any{"type": "string"}, "open_files": map[string]any{"type": "array", "items": map[string]any{"type": "string"}}, "selected_text": map[string]any{"type": "string"}, "selection_start_line": map[string]any{"type": "integer"}, "selection_end_line": map[string]any{"type": "integer"}, "language_id": map[string]any{"type": "string"}, "diagnostics": map[string]any{"type": "array", "items": map[string]any{"type": "object"}}}}},
		{"name": "pac_update_editor_state", "description": "Update active editor state for an existing PAC session.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"session_id": map[string]any{"type": "string"}, "editor": map[string]any{"type": "string"}, "workspace_root": map[string]any{"type": "string"}, "active_file": map[string]any{"type": "string"}, "open_files": map[string]any{"type": "array", "items": map[string]any{"type": "string"}}, "selected_text": map[string]any{"type": "string"}, "selection_start_line": map[string]any{"type": "integer"}, "selection_end_line": map[string]any{"type": "integer"}, "language_id": map[string]any{"type": "string"}, "diagnostics": map[string]any{"type": "array", "items": map[string]any{"type": "object"}}}, "required": []string{"session_id"}}},
		{"name": "pac_list_models", "description": "List configured PAC models.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
		{"name": "pac_list_providers", "description": "List configured PAC model providers.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
		{"name": "pac_list_tools", "description": "List PAC tool configuration.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{}}},
		{"name": "pac_create_session", "description": "Create a PAC session.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"name": map[string]any{"type": "string"}, "agent_profile": map[string]any{"type": "string"}, "workspace_profile": map[string]any{"type": "string"}, "permission_profile": map[string]any{"type": "string"}, "model": map[string]any{"type": "string"}, "workspace_path": map[string]any{"type": "string"}, "git_url": map[string]any{"type": "string"}, "git_branch": map[string]any{"type": "string"}}}},
		{"name": "pac_run_task", "description": "Run a prompt or command in a PAC session.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"session_id": map[string]any{"type": "string"}, "prompt": map[string]any{"type": "string"}, "command": map[string]any{"type": "string"}, "wait": map[string]any{"type": "boolean"}}, "required": []string{"session_id", "prompt"}}},
		{"name": "pac_get_events", "description": "Get recent events for a PAC session.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"session_id": map[string]any{"type": "string"}}, "required": []string{"session_id"}}},
		{"name": "pac_git_diff", "description": "Get git diff for a PAC session.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"session_id": map[string]any{"type": "string"}}, "required": []string{"session_id"}}},
		{"name": "pac_add_timeline_event", "description": "Add a structured PAC timeline event. Use data.timeline with format pac.timeline.v1 for rich cards instead of plain Markdown.", "inputSchema": map[string]any{"type": "object", "properties": map[string]any{"session_id": map[string]any{"type": "string"}, "type": map[string]any{"type": "string"}, "message": map[string]any{"type": "string"}, "data": map[string]any{"type": "object", "properties": map[string]any{}}}, "required": []string{"session_id", "message"}}},
	}
}

func toolCall(c *client, name string, args map[string]any) (any, error) {
	switch name {
	case "pac_version":
		return c.req("GET", "/v1/version", nil)
	case "pac_list_agent_contexts":
		return c.req("GET", "/v1/agent-contexts", nil)
	case "pac_list_my_workspaces":
		return c.req("GET", "/v1/my-workspaces", nil)
	case "pac_bootstrap_editor_session":
		body := map[string]any{
			"origin":               valueOrDefault(args["origin"], "zed"),
			"context_id":           args["context_id"],
			"workspace_id":         args["workspace_id"],
			"editor":               args["editor"],
			"workspace_root":       args["workspace_root"],
			"active_file":          args["active_file"],
			"open_files":           listArg(args["open_files"]),
			"selected_text":        args["selected_text"],
			"selection_start_line": args["selection_start_line"],
			"selection_end_line":   args["selection_end_line"],
			"language_id":          args["language_id"],
			"diagnostics":          objectListArg(args["diagnostics"]),
		}
		return c.req("POST", "/v1/editor/bootstrap", body)
	case "pac_update_editor_state":
		sid, _ := args["session_id"].(string)
		if sid == "" {
			return nil, fmt.Errorf("session_id is required")
		}
		body := map[string]any{
			"editor":               args["editor"],
			"workspace_root":       args["workspace_root"],
			"active_file":          args["active_file"],
			"open_files":           listArg(args["open_files"]),
			"selected_text":        args["selected_text"],
			"selection_start_line": args["selection_start_line"],
			"selection_end_line":   args["selection_end_line"],
			"language_id":          args["language_id"],
			"diagnostics":          objectListArg(args["diagnostics"]),
		}
		return c.req("POST", "/v1/editor/sessions/"+sid+"/state", body)
	case "pac_list_models":
		return c.req("GET", "/v1/models", nil)
	case "pac_list_providers":
		return c.req("GET", "/v1/providers", nil)
	case "pac_list_tools":
		return c.req("GET", "/v1/tools", nil)
	case "pac_create_session":
		workspace := map[string]any{"type": "local", "path": args["workspace_path"]}
		if v, ok := args["workspace_profile"].(string); ok && v != "" {
			workspace = map[string]any{"type": "profile", "profile": v}
		}
		if v, ok := args["git_url"].(string); ok && v != "" {
			workspace = map[string]any{"type": "git", "url": v, "branch": args["git_branch"], "path": args["workspace_path"]}
		}
		body := map[string]any{"name": args["name"], "agent_profile": args["agent_profile"], "permission_profile": args["permission_profile"], "model": args["model"], "workspace": workspace}
		return c.req("POST", "/v1/sessions", body)
	case "pac_run_task":
		sid, _ := args["session_id"].(string)
		if sid == "" {
			return nil, fmt.Errorf("session_id is required")
		}
		wait := ""
		if b, _ := args["wait"].(bool); b {
			wait = "?wait=true"
		}
		body := map[string]any{"prompt": args["prompt"], "command": args["command"]}
		return c.req("POST", "/v1/sessions/"+sid+"/tasks"+wait, body)
	case "pac_get_events":
		sid, _ := args["session_id"].(string)
		return c.req("GET", "/v1/sessions/"+sid+"/events/snapshot", nil)
	case "pac_git_diff":
		sid, _ := args["session_id"].(string)
		return c.req("GET", "/v1/sessions/"+sid+"/diff", nil)
	case "pac_add_timeline_event":
		sid, _ := args["session_id"].(string)
		if sid == "" {
			return nil, fmt.Errorf("session_id is required")
		}
		body := map[string]any{
			"type":    args["type"],
			"message": args["message"],
			"data":    args["data"],
		}
		return c.req("POST", "/v1/sessions/"+sid+"/events", body)
	default:
		return nil, fmt.Errorf("unknown tool: %s", name)
	}
}

func valueOrDefault(value any, fallback string) string {
	if text, ok := value.(string); ok && strings.TrimSpace(text) != "" {
		return strings.TrimSpace(text)
	}
	return fallback
}

func listArg(value any) []string {
	if value == nil {
		return []string{}
	}
	if typed, ok := value.([]string); ok {
		return typed
	}
	raw, ok := value.([]any)
	if !ok {
		return []string{}
	}
	out := make([]string, 0, len(raw))
	for _, item := range raw {
		if text, ok := item.(string); ok && strings.TrimSpace(text) != "" {
			out = append(out, strings.TrimSpace(text))
		}
	}
	return out
}

func objectListArg(value any) []map[string]any {
	if value == nil {
		return []map[string]any{}
	}
	if typed, ok := value.([]map[string]any); ok {
		return typed
	}
	raw, ok := value.([]any)
	if !ok {
		return []map[string]any{}
	}
	out := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		if obj, ok := item.(map[string]any); ok {
			out = append(out, obj)
		}
	}
	return out
}

func main() {
	os.Args = append(os.Args[:1], applyEnvAssignments(os.Args[1:])...)
	baseDefault := strings.TrimSpace(os.Getenv("PAC_URL"))
	if baseDefault == "" {
		baseDefault = defaultServerURL
	}
	base := flag.String("base-url", baseDefault, "PAC base URL")
	token := flag.String("token", os.Getenv("PAC_TOKEN"), "PAC bearer token")
	insecureDefault := strings.EqualFold(strings.TrimSpace(os.Getenv("PAC_INSECURE")), "1") || strings.EqualFold(strings.TrimSpace(os.Getenv("PAC_INSECURE")), "true")
	insecure := flag.Bool("insecure", insecureDefault, "skip TLS certificate verification when connecting to PAC")
	check := flag.Bool("check", false, "check PAC connectivity and exit")
	flag.Parse()
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if *insecure {
		transport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}
	}
	c := &client{base: strings.TrimRight(*base, "/"), token: *token, http: &http.Client{Timeout: 20 * time.Second, Transport: transport}}
	if *check {
		res, err := c.req("GET", "/v1/version", nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		b, _ := json.MarshalIndent(res, "", "  ")
		fmt.Println(string(b))
		return
	}
	if info, err := os.Stdin.Stat(); err == nil && (info.Mode()&os.ModeCharDevice) != 0 {
		fmt.Fprintf(os.Stderr, "pac zed MCP helper %s\n", version)
		fmt.Fprintf(os.Stderr, "This binary is a stdio MCP server. Configure it in Zed, or run with --check to test PAC connectivity.\n")
		fmt.Fprintf(os.Stderr, "PAC URL: %s\n", c.base)
		return
	}
	dec := json.NewDecoder(os.Stdin)
	for {
		var req rpcReq
		if err := dec.Decode(&req); err != nil {
			if err == io.EOF {
				return
			}
			write(rpcResp{JSONRPC: "2.0", Error: map[string]any{"code": -32700, "message": err.Error()}})
			continue
		}
		switch req.Method {
		case "initialize":
			write(rpcResp{JSONRPC: "2.0", ID: req.ID, Result: map[string]any{"protocolVersion": "2024-11-05", "serverInfo": map[string]any{"name": "pac", "version": version}, "capabilities": map[string]any{"tools": map[string]any{}}}})
		case "tools/list":
			write(rpcResp{JSONRPC: "2.0", ID: req.ID, Result: map[string]any{"tools": tools()}})
		case "tools/call":
			var p struct {
				Name      string         `json:"name"`
				Arguments map[string]any `json:"arguments"`
			}
			json.Unmarshal(req.Params, &p)
			res, err := toolCall(c, p.Name, p.Arguments)
			if err != nil {
				write(rpcResp{JSONRPC: "2.0", ID: req.ID, Error: map[string]any{"code": -32000, "message": err.Error()}})
				continue
			}
			b, _ := json.MarshalIndent(res, "", "  ")
			write(rpcResp{JSONRPC: "2.0", ID: req.ID, Result: map[string]any{"content": []map[string]any{{"type": "text", "text": string(b)}}}})
		default:
			if req.ID != nil {
				write(rpcResp{JSONRPC: "2.0", ID: req.ID, Error: map[string]any{"code": -32601, "message": "unknown method: " + req.Method}})
			}
		}
	}
}
