package main

import (
  "bytes"
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

type client struct { base string; token string; http *http.Client }

func (c *client) req(method, path string, body any) (any, error) {
  var r io.Reader
  if body != nil { b, _ := json.Marshal(body); r = bytes.NewReader(b) }
  req, err := http.NewRequest(method, c.base + path, r)
  if err != nil { return nil, err }
  req.Header.Set("Content-Type", "application/json")
  if c.token != "" { req.Header.Set("Authorization", "Bearer " + c.token) }
  resp, err := c.http.Do(req)
  if err != nil { return nil, err }
  defer resp.Body.Close()
  data, _ := io.ReadAll(resp.Body)
  if resp.StatusCode < 200 || resp.StatusCode >= 300 { return nil, fmt.Errorf("PAC HTTP %d: %s", resp.StatusCode, string(data)) }
  if len(data) == 0 { return map[string]any{"ok": true}, nil }
  var out any
  if err := json.Unmarshal(data, &out); err != nil { return string(data), nil }
  return out, nil
}

func write(v any) { b, _ := json.Marshal(v); fmt.Println(string(b)) }

func tools() []map[string]any {
  return []map[string]any{
    {"name":"pac_version","description":"Get PAC server version.","inputSchema":map[string]any{"type":"object","properties":map[string]any{}}},
    {"name":"pac_list_models","description":"List configured PAC models.","inputSchema":map[string]any{"type":"object","properties":map[string]any{}}},
    {"name":"pac_list_providers","description":"List configured PAC model providers.","inputSchema":map[string]any{"type":"object","properties":map[string]any{}}},
    {"name":"pac_list_tools","description":"List PAC tool configuration.","inputSchema":map[string]any{"type":"object","properties":map[string]any{}}},
    {"name":"pac_create_session","description":"Create a PAC session.","inputSchema":map[string]any{"type":"object","properties":map[string]any{"name":map[string]any{"type":"string"},"agent_profile":map[string]any{"type":"string"},"workspace_profile":map[string]any{"type":"string"},"permission_profile":map[string]any{"type":"string"},"model":map[string]any{"type":"string"},"workspace_path":map[string]any{"type":"string"},"git_url":map[string]any{"type":"string"},"git_branch":map[string]any{"type":"string"}}}},
    {"name":"pac_run_task","description":"Run a prompt or command in a PAC session.","inputSchema":map[string]any{"type":"object","properties":map[string]any{"session_id":map[string]any{"type":"string"},"prompt":map[string]any{"type":"string"},"command":map[string]any{"type":"string"},"wait":map[string]any{"type":"boolean"}},"required":[]string{"session_id","prompt"}}},
    {"name":"pac_get_events","description":"Get recent events for a PAC session.","inputSchema":map[string]any{"type":"object","properties":map[string]any{"session_id":map[string]any{"type":"string"}},"required":[]string{"session_id"}}},
    {"name":"pac_git_diff","description":"Get git diff for a PAC session.","inputSchema":map[string]any{"type":"object","properties":map[string]any{"session_id":map[string]any{"type":"string"}},"required":[]string{"session_id"}}},
  }
}

func toolCall(c *client, name string, args map[string]any) (any, error) {
  switch name {
  case "pac_version": return c.req("GET", "/v1/version", nil)
  case "pac_list_models": return c.req("GET", "/v1/models", nil)
  case "pac_list_providers": return c.req("GET", "/v1/providers", nil)
  case "pac_list_tools": return c.req("GET", "/v1/tools", nil)
  case "pac_create_session":
    workspace := map[string]any{"type":"local", "path": args["workspace_path"]}
    if v, ok := args["workspace_profile"].(string); ok && v != "" { workspace = map[string]any{"type":"profile", "profile":v} }
    if v, ok := args["git_url"].(string); ok && v != "" { workspace = map[string]any{"type":"git", "url":v, "branch":args["git_branch"], "path":args["workspace_path"]} }
    body := map[string]any{"name":args["name"],"agent_profile":args["agent_profile"],"permission_profile":args["permission_profile"],"model":args["model"],"workspace":workspace}
    return c.req("POST", "/v1/sessions", body)
  case "pac_run_task":
    sid, _ := args["session_id"].(string); if sid == "" { return nil, fmt.Errorf("session_id is required") }
    wait := ""; if b, _ := args["wait"].(bool); b { wait = "?wait=true" }
    body := map[string]any{"prompt": args["prompt"], "command": args["command"]}
    return c.req("POST", "/v1/sessions/"+sid+"/tasks"+wait, body)
  case "pac_get_events":
    sid, _ := args["session_id"].(string); return c.req("GET", "/v1/sessions/"+sid+"/events/snapshot", nil)
  case "pac_git_diff":
    sid, _ := args["session_id"].(string); return c.req("GET", "/v1/sessions/"+sid+"/diff", nil)
  default: return nil, fmt.Errorf("unknown tool: %s", name)
  }
}

func main() {
  base := flag.String("base-url", "https://localhost", "PAC base URL")
  token := flag.String("token", os.Getenv("PAC_TOKEN"), "PAC bearer token")
  flag.Parse()
  c := &client{base: strings.TrimRight(*base, "/"), token:*token, http:&http.Client{Timeout: 300*time.Second}}
  dec := json.NewDecoder(os.Stdin)
  for {
    var req rpcReq
    if err := dec.Decode(&req); err != nil { if err == io.EOF { return }; write(rpcResp{JSONRPC:"2.0", Error:map[string]any{"code":-32700,"message":err.Error()}}); continue }
    switch req.Method {
    case "initialize":
      write(rpcResp{JSONRPC:"2.0", ID:req.ID, Result:map[string]any{"protocolVersion":"2024-11-05","serverInfo":map[string]any{"name":"pac","version":version},"capabilities":map[string]any{"tools":map[string]any{}}}})
    case "tools/list":
      write(rpcResp{JSONRPC:"2.0", ID:req.ID, Result:map[string]any{"tools": tools()}})
    case "tools/call":
      var p struct { Name string `json:"name"`; Arguments map[string]any `json:"arguments"` }
      json.Unmarshal(req.Params, &p)
      res, err := toolCall(c, p.Name, p.Arguments)
      if err != nil { write(rpcResp{JSONRPC:"2.0", ID:req.ID, Error:map[string]any{"code":-32000,"message":err.Error()}}); continue }
      b, _ := json.MarshalIndent(res, "", "  ")
      write(rpcResp{JSONRPC:"2.0", ID:req.ID, Result:map[string]any{"content":[]map[string]any{{"type":"text","text":string(b)}}}})
    default:
      if req.ID != nil { write(rpcResp{JSONRPC:"2.0", ID:req.ID, Error:map[string]any{"code":-32601,"message":"unknown method: "+req.Method}}) }
    }
  }
}
