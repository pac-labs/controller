package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

type workspaceConfig struct {
	WorkspaceID   string         `json:"workspace_id"`
	Name          string         `json:"name"`
	ControllerURL string         `json:"controller_url"`
	Token         string         `json:"token"`
	Root          string         `json:"root"`
	Lifetime      string         `json:"lifetime"`
	Labels        []string       `json:"labels"`
	Capabilities  map[string]any `json:"capabilities"`
	Metadata      map[string]any `json:"metadata"`
}

type workspaceRegistration struct {
	ID string `json:"id"`
}

func workspaceModeRequested(args []string) bool {
	return len(args) >= 2 && args[0] == "workspace" && (args[1] == "run" || args[1] == "register")
}

func runWorkspaceMode(ctx context.Context, args []string) int {
	cfg := loadWorkspaceConfig(args)
	if cfg.ControllerURL == "" {
		fmt.Fprintln(os.Stderr, "PAC_URL or PAC_CONTROLLER_URL is required for workspace mode")
		return 2
	}
	if cfg.Root == "" {
		cfg.Root = env("PAC_WORKSPACE", "/workspace")
	}
	if cfg.Name == "" {
		cfg.Name = cfg.WorkspaceID
	}
	if cfg.Name == "" {
		host, _ := os.Hostname()
		cfg.Name = host
	}
	if cfg.Lifetime == "" {
		cfg.Lifetime = "persistent"
	}
	if cfg.Capabilities == nil {
		cfg.Capabilities = map[string]any{"shell": true, "files": true, "git": true, "tools": true}
	}
	if cfg.Metadata == nil {
		cfg.Metadata = map[string]any{}
	}
	cfg.Metadata["binary"] = binaryName
	cfg.Metadata["version"] = version
	cfg.Metadata["os"] = runtime.GOOS
	cfg.Metadata["arch"] = runtime.GOARCH
	cfg.Metadata["mode"] = "workspace"
	cfg.Metadata["inventory"] = endpointInventory(cfg.Root)
	cfg.Metadata["metrics"] = endpointMetrics(cfg.Root)

	client := Client{base: strings.TrimRight(cfg.ControllerURL, "/"), token: cfg.Token, http: newHTTPClient()}
	workspaceID, endpointID := registerWorkspace(ctx, client, cfg)
	if args[1] == "register" {
		fmt.Printf("PAC workspace %s registered\n", workspaceID)
		return 0
	}
	fmt.Printf("PAC workspace %s online; waiting for routed commands\n", workspaceID)
	return workspaceLoop(ctx, client, cfg, workspaceID, endpointID)
}

func loadWorkspaceConfig(args []string) workspaceConfig {
	cfg := workspaceConfig{}
	path := flagArg(args, "--config")
	if path == "" {
		for _, candidate := range []string{"/etc/pac/workspace.json", "/pac/workspace.json", "workspace.pac.json"} {
			if _, err := os.Stat(candidate); err == nil {
				path = candidate
				break
			}
		}
	}
	if path != "" {
		if data, err := os.ReadFile(path); err == nil {
			_ = json.Unmarshal(data, &cfg)
		}
	}
	if value := env("PAC_CONTROLLER_URL", env("PAC_URL", cfg.ControllerURL)); value != "" {
		cfg.ControllerURL = value
	}
	if value := env("PAC_WORKSPACE_TOKEN", env("PAC_TOKEN", cfg.Token)); value != "" {
		cfg.Token = value
	}
	if value := env("PAC_WORKSPACE_ID", cfg.WorkspaceID); value != "" {
		cfg.WorkspaceID = value
	}
	if value := env("PAC_WORKSPACE_NAME", cfg.Name); value != "" {
		cfg.Name = value
	}
	if value := env("PAC_WORKSPACE_ROOT", cfg.Root); value != "" {
		cfg.Root = value
	}
	if value := env("PAC_WORKSPACE_LIFETIME", cfg.Lifetime); value != "" {
		cfg.Lifetime = value
	}
	if labels := env("PAC_WORKSPACE_LABELS", ""); labels != "" {
		cfg.Labels = splitCSV(labels)
	}
	if value := flagArg(args, "--id"); value != "" {
		cfg.WorkspaceID = value
	}
	if value := flagArg(args, "--name"); value != "" {
		cfg.Name = value
	}
	if value := flagArg(args, "--root"); value != "" {
		cfg.Root = value
	}
	return cfg
}

func registerWorkspace(ctx context.Context, client Client, cfg workspaceConfig) (string, string) {
	payload := map[string]any{
		"workspace_id": cfg.WorkspaceID,
		"name":         cfg.Name,
		"root":         cfg.Root,
		"lifetime":     cfg.Lifetime,
		"labels":       cfg.Labels,
		"capabilities": cfg.Capabilities,
		"metadata":     cfg.Metadata,
	}
	data, code, err := client.request(ctx, "POST", "/v1/workspace-agents/register", payload)
	if err == nil && code < 300 {
		var out map[string]any
		_ = json.Unmarshal(data, &out)
		id := firstString(out, "workspace_id", "id")
		agentID := firstString(out, "agent_id", "endpoint_id")
		if id != "" {
			return id, agentID
		}
	}
	endpointName := cfg.WorkspaceID
	if endpointName == "" {
		endpointName = cfg.Name
	}
	fallback := map[string]any{
		"name":                      endpointName,
		"labels":                    append([]string{"workspace", "container", runtime.GOOS, runtime.GOARCH}, cfg.Labels...),
		"endpoint":                  "pac-workspace://" + endpointName,
		"allow_host_execution":      false,
		"allow_container_execution": true,
		"agent_enabled":             true,
		"metadata":                  payload,
	}
	runner := registerWithRetry(ctx, client, fallback, endpointName, true)
	return endpointName, runner.ID
}

func workspaceLoop(ctx context.Context, client Client, cfg workspaceConfig, workspaceID, endpointID string) int {
	for {
		heartbeatMetadata := map[string]any{}
		for key, value := range cfg.Metadata {
			heartbeatMetadata[key] = value
		}
		heartbeatMetadata["inventory"] = endpointInventory(cfg.Root)
		heartbeatMetadata["metrics"] = endpointMetrics(cfg.Root)
		heartbeat := map[string]any{
			"workspace_id": workspaceID,
			"endpoint_id":  endpointID,
			"status":       "online",
			"version":      version,
			"root":         cfg.Root,
			"labels":       cfg.Labels,
			"capabilities": cfg.Capabilities,
			"metadata":     heartbeatMetadata,
			"inventory":    heartbeatMetadata["inventory"],
			"metrics":      heartbeatMetadata["metrics"],
		}
		_, code, err := client.request(ctx, "POST", "/v1/workspace-agents/heartbeat", heartbeat)
		if err != nil || code >= 300 {
			fallback := map[string]any{"runner_id": endpointID, "status": "online", "version": version, "labels": []string{"workspace", "container"}, "metadata": heartbeat}
			_, _, _ = client.request(ctx, "POST", "/v1/endpoints/heartbeat", fallback)
		}
		pollWorkspaceCommand(ctx, client, cfg, workspaceID, endpointID)
		time.Sleep(5 * time.Second)
	}
}

func pollWorkspaceCommand(ctx context.Context, client Client, cfg workspaceConfig, workspaceID, endpointID string) {
	paths := []string{"/v1/workspace-agents/" + url.PathEscape(workspaceID) + "/commands/next"}
	if endpointID != "" {
		paths = append(paths, "/v1/endpoints/"+url.PathEscape(endpointID)+"/jobs/next")
	}
	for _, path := range paths {
		data, code, err := client.request(ctx, "GET", path, nil)
		if err != nil || code != 200 || strings.TrimSpace(string(data)) == "" || strings.TrimSpace(string(data)) == "null" {
			continue
		}
		var job Job
		if json.Unmarshal(data, &job) != nil || job.ID == "" {
			continue
		}
		if strings.TrimSpace(job.WorkspacePath) == "" {
			job.WorkspacePath = cfg.Root
		}
		emit := func(stream, chunk string) {
			event := map[string]any{"stream": stream, "data": chunk, "metadata": map[string]any{"workspace_id": workspaceID, "endpoint_version": version}}
			_, _, _ = client.request(ctx, "POST", "/v1/workspace-agents/"+url.PathEscape(workspaceID)+"/commands/"+url.PathEscape(job.ID)+"/events", event)
		}
		cancelCheck := func() bool {
			return workspaceCommandCancelRequested(ctx, client, workspaceID, job.ID)
		}
		exit, out, stderr := runCommandStreamingCancelable(job, emit, cancelCheck)
		status := "completed"
		if exit == 130 {
			status = "interrupted"
		} else if exit != 0 {
			status = "failed"
		}
		complete := map[string]any{"status": status, "output": out, "error": stderr, "exit_code": exit, "metadata": map[string]any{"workspace_id": workspaceID, "endpoint_version": version, "streamed": true}}
		_, code, _ = client.request(ctx, "POST", "/v1/workspace-agents/"+url.PathEscape(workspaceID)+"/commands/"+url.PathEscape(job.ID)+"/complete", complete)
		if code >= 300 && endpointID != "" {
			_, _, _ = client.request(ctx, "POST", "/v1/runner-jobs/"+url.PathEscape(job.ID), complete)
		}
		return
	}
}

func workspaceCommandCancelRequested(ctx context.Context, client Client, workspaceID, commandID string) bool {
	data, code, err := client.request(ctx, "GET", "/v1/workspaces/"+url.PathEscape(workspaceID)+"/commands/"+url.PathEscape(commandID), nil)
	if err != nil || code >= 300 || len(strings.TrimSpace(string(data))) == 0 {
		return false
	}
	var root map[string]any
	if json.Unmarshal(data, &root) != nil {
		return false
	}
	command, _ := root["command"].(map[string]any)
	if command == nil {
		return false
	}
	status := strings.TrimSpace(fmt.Sprint(command["status"]))
	if status == "interrupted" {
		return true
	}
	metadata, _ := command["metadata"].(map[string]any)
	if metadata == nil {
		return false
	}
	if requested, _ := metadata["cancel_requested"].(bool); requested {
		return true
	}
	return strings.EqualFold(strings.TrimSpace(fmt.Sprint(metadata["cancel_requested"])), "true")
}

func flagArg(args []string, name string) string {
	for i := 0; i < len(args)-1; i++ {
		if args[i] == name {
			return strings.TrimSpace(args[i+1])
		}
	}
	return ""
}

func splitCSV(value string) []string {
	parts := strings.Split(value, ",")
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}

func firstString(data map[string]any, keys ...string) string {
	for _, key := range keys {
		if value := strings.TrimSpace(fmt.Sprint(data[key])); value != "" && value != "<nil>" {
			return value
		}
	}
	return ""
}

func ensureWorkspaceRoot(root string) string {
	if root == "" {
		return ""
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return root
	}
	_ = os.MkdirAll(abs, 0750)
	return abs
}
