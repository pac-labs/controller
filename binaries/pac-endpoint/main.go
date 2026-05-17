package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
)

var version = "dev"
var defaultServerURL = ""
var defaultControllerID = ""
var defaultUpdateChannel = "stable"
var defaultEndpointName = ""
var defaultRunnerEnabled = "true"
var defaultWorkspaceRoot = ""

const binaryName = "pac-endpoint"

type Runner struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}
type Job struct {
	ID            string         `json:"id"`
	Prompt        string         `json:"prompt"`
	Command       string         `json:"command"`
	ExecutionMode string         `json:"execution_mode"`
	WorkspacePath string         `json:"workspace_path"`
	Metadata      map[string]any `json:"metadata"`
}

type ToolSpec struct {
	Name        string   `json:"name"`
	Binary      string   `json:"binary"`
	Binaries    []string `json:"binaries"`
	Required    bool     `json:"required"`
	Description string   `json:"description"`
}

type ToolState struct {
	Available   bool     `json:"available"`
	Path        string   `json:"path,omitempty"`
	Required    bool     `json:"required"`
	Description string   `json:"description,omitempty"`
	Binaries    []string `json:"binaries,omitempty"`
}

var endpointToolSpecs = []ToolSpec{
	{Name: "ripgrep", Binary: "rg", Required: true, Description: "fast code/content search"},
	{Name: "fd", Binary: "fd", Required: true, Description: "fast file discovery"},
	{Name: "jq", Binary: "jq", Required: true, Description: "JSON parsing and shaping"},
	{Name: "git", Binary: "git", Required: true, Description: "repository operations"},
	{Name: "delta", Binary: "delta", Required: true, Description: "human-readable git diffs"},
	{Name: "bat", Binary: "bat", Binaries: []string{"bat", "batcat", "bad"}, Required: true, Description: "file preview with syntax highlighting"},
	{Name: "just", Binary: "just", Required: true, Description: "project command runner"},
}

func toolSpecByName(name string) (ToolSpec, bool) {
	for _, spec := range endpointToolSpecs {
		if spec.Name == name || spec.Binary == name {
			return spec, true
		}
		for _, bin := range spec.Binaries {
			if bin == name {
				return spec, true
			}
		}
	}
	return ToolSpec{}, false
}

type Client struct {
	base, token string
	http        *http.Client
}

type registerAttemptState struct {
	Key      string
	Attempts int
}

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

func env(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	v := strings.ToLower(strings.TrimSpace(os.Getenv(key)))
	if v == "" {
		return fallback
	}
	switch v {
	case "1", "true", "yes", "on", "enabled":
		return true
	case "0", "false", "no", "off", "disabled":
		return false
	default:
		return fallback
	}
}

func newHTTPClient() *http.Client {
	tr := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}}
	caFile := strings.TrimSpace(os.Getenv("PAC_CA_FILE"))
	if caFile != "" {
		if pem, err := os.ReadFile(caFile); err == nil {
			pool, _ := x509.SystemCertPool()
			if pool == nil {
				pool = x509.NewCertPool()
			}
			pool.AppendCertsFromPEM(pem)
			tr.TLSClientConfig.RootCAs = pool
		}
	}
	certFile, keyFile := strings.TrimSpace(os.Getenv("PAC_CLIENT_CERT")), strings.TrimSpace(os.Getenv("PAC_CLIENT_KEY"))
	if certFile != "" && keyFile != "" {
		if cert, err := tls.LoadX509KeyPair(certFile, keyFile); err == nil {
			tr.TLSClientConfig.Certificates = []tls.Certificate{cert}
		}
	}
	return &http.Client{Timeout: 60 * time.Second, Transport: tr}
}

func (c Client) request(ctx context.Context, method, path string, body any) ([]byte, int, error) {
	var r io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		r = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, r)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", binaryName+"/"+version+" "+runtime.GOOS+"/"+runtime.GOARCH)
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	return data, resp.StatusCode, nil
}

func commandShell(command string) *exec.Cmd {
	shell := "/bin/sh"
	arg := "-lc"
	if runtime.GOOS == "windows" {
		shell = "cmd"
		arg = "/C"
	}
	return exec.Command(shell, arg, command)
}

func workspaceRoot(job Job) (string, error) {
	root := strings.TrimSpace(job.WorkspacePath)
	if root == "" {
		fallback := strings.TrimSpace(defaultWorkspaceRoot)
		if fallback == "" {
			fallback = filepath.Join(os.TempDir(), "pac-endpoint-workspace")
		}
		root = env("PAC_WORKSPACE", fallback)
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(abs, 0750); err != nil {
		return "", err
	}
	return abs, nil
}

func runCommand(job Job) (int, string, string) {
	root, err := workspaceRoot(job)
	if err != nil {
		return 1, "", err.Error()
	}
	cmd := commandShell(job.Command)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PAC_WORKSPACE="+root, "PAC_JOB_ID="+job.ID, "PAC_ENDPOINT_VERSION="+version)
	var out, er bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &er
	err = cmd.Run()
	code := 0
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			code = ee.ExitCode()
		} else {
			code = 1
			er.WriteString(err.Error())
		}
	}
	return code, out.String(), er.String()
}

func stringMeta(m map[string]any, key string) string {
	if m == nil {
		return ""
	}
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func selfUpdate(job Job) (int, string, string) {
	url := stringMeta(job.Metadata, "artifact_url")
	wantSHA := strings.ToLower(strings.TrimSpace(stringMeta(job.Metadata, "sha256")))
	if url == "" {
		return 1, "", "self update needs metadata.artifact_url"
	}
	current, err := os.Executable()
	if err != nil {
		return 1, "", err.Error()
	}
	tmp := current + ".new"
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	resp, err := newHTTPClient().Do(req)
	if err != nil {
		return 1, "", err.Error()
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return 1, "", fmt.Sprintf("download failed: HTTP %d", resp.StatusCode)
	}
	h := sha256.New()
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0755)
	if err != nil {
		return 1, "", err.Error()
	}
	if _, err := io.Copy(io.MultiWriter(f, h), resp.Body); err != nil {
		f.Close()
		return 1, "", err.Error()
	}
	f.Close()
	got := hex.EncodeToString(h.Sum(nil))
	if wantSHA != "" && got != wantSHA {
		os.Remove(tmp)
		return 1, "", "sha256 mismatch"
	}
	backup := current + ".old"
	_ = os.Remove(backup)
	if err := os.Rename(current, backup); err != nil {
		os.Remove(tmp)
		return 1, "", err.Error()
	}
	if err := os.Rename(tmp, current); err != nil {
		_ = os.Rename(backup, current)
		return 1, "", err.Error()
	}
	return 0, "endpoint binary updated; restart the endpoint process to use the new version\n", ""
}

func stringSliceMeta(m map[string]any, key string) []string {
	if m == nil {
		return nil
	}
	switch v := m[key].(type) {
	case []string:
		return v
	case []any:
		out := make([]string, 0, len(v))
		for _, item := range v {
			out = append(out, fmt.Sprint(item))
		}
		return out
	case string:
		if v == "" {
			return nil
		}
		return []string{v}
	default:
		return nil
	}
}

func stdinMeta(m map[string]any) string {
	if m == nil {
		return ""
	}
	if v, ok := m["stdin"].(string); ok {
		return v
	}
	return ""
}

func discoverEndpointTools() map[string]ToolState {
	tools := map[string]ToolState{}
	for _, spec := range endpointToolSpecs {
		bins := spec.Binaries
		if len(bins) == 0 {
			bins = []string{spec.Binary}
		}
		state := ToolState{Available: false, Required: spec.Required, Description: spec.Description, Binaries: bins}
		for _, bin := range bins {
			if p, err := exec.LookPath(bin); err == nil {
				state.Available = true
				state.Path = p
				break
			}
		}
		tools[spec.Name] = state
	}
	// Keep common runtime names visible too, but do not make them part of the required agent tool set.
	for _, opt := range []string{"node", "podman", "docker", "bash", "sh"} {
		if p, err := exec.LookPath(opt); err == nil {
			tools[opt] = ToolState{Available: true, Path: p, Required: false}
		} else if _, exists := tools[opt]; !exists {
			tools[opt] = ToolState{Available: false, Required: false}
		}
	}
	return tools
}

func requiredToolSummary(tools map[string]ToolState) map[string]any {
	required := []string{}
	missing := []string{}
	available := []string{}
	for _, spec := range endpointToolSpecs {
		required = append(required, spec.Name)
		if tools[spec.Name].Available {
			available = append(available, spec.Name)
		} else {
			missing = append(missing, spec.Name)
		}
	}
	sort.Strings(required)
	sort.Strings(available)
	sort.Strings(missing)
	return map[string]any{"required": required, "available": available, "missing": missing, "ready": len(missing) == 0}
}

func runToolInvocation(job Job) (int, string, string) {
	toolName := strings.TrimSpace(stringMeta(job.Metadata, "tool_name"))
	if toolName == "" {
		return 1, "", "metadata.tool_name is required for tool invocation"
	}
	spec, ok := toolSpecByName(toolName)
	if !ok {
		return 1, "", fmt.Sprintf("tool %q is not registered on this endpoint", toolName)
	}
	tools := discoverEndpointTools()
	state := tools[spec.Name]
	if !state.Available || state.Path == "" {
		return 127, "", fmt.Sprintf("required endpoint tool %q is missing; install one of: %s", spec.Name, strings.Join(state.Binaries, ", "))
	}
	root, err := workspaceRoot(job)
	if err != nil {
		return 1, "", err.Error()
	}
	args := stringSliceMeta(job.Metadata, "args")
	cmd := exec.Command(state.Path, args...)
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PAC_WORKSPACE="+root, "PAC_JOB_ID="+job.ID, "PAC_ENDPOINT_VERSION="+version, "PAC_TOOL_NAME="+spec.Name)
	if stdin := stdinMeta(job.Metadata); stdin != "" {
		cmd.Stdin = strings.NewReader(stdin)
	}
	var out, er bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &er
	err = cmd.Run()
	code := 0
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			code = ee.ExitCode()
		} else {
			code = 1
			er.WriteString(err.Error())
		}
	}
	return code, out.String(), er.String()
}

func runtimeCapabilities(runnerEnabled bool) map[string]any {
	workspace := env("PAC_WORKSPACE", filepath.Join(os.TempDir(), "pac-endpoint-workspace"))
	tools := discoverEndpointTools()
	caps := map[string]any{
		"os":        runtime.GOOS,
		"arch":      runtime.GOARCH,
		"version":   version,
		"binary":    binaryName,
		"workspace": workspace,
		"runner": map[string]any{
			"available": true,
			"embedded":  true,
			"enabled":   runnerEnabled,
			"workspace": workspace,
		},
		"tools":                 tools,
		"agent_required_tools":  requiredToolSummary(tools),
		"tool_execution_bridge": map[string]any{"available": runnerEnabled, "mode": "named-tool", "returns": []string{"stdout", "stderr", "exit_code"}},
	}
	if p, err := exec.LookPath("node"); err == nil {
		caps["node"] = map[string]any{"available": true, "path": p}
	} else {
		caps["node"] = map[string]any{"available": false}
	}
	if p, err := exec.LookPath("podman"); err == nil {
		caps["podman"] = map[string]any{"available": true, "path": p}
	}
	if p, err := exec.LookPath("docker"); err == nil {
		caps["docker"] = map[string]any{"available": true, "path": p}
	}
	return caps
}

func classifyRegisterFailure(err error, code int, data []byte) (string, string) {
	body := strings.TrimSpace(string(data))
	switch {
	case code == http.StatusUnauthorized:
		return "auth_missing", "endpoint registration is missing authorization; check PAC_TOKEN or the controller service token"
	case code == http.StatusForbidden:
		return "auth_forbidden", "endpoint registration is forbidden; verify the controller service token or endpoint auth policy"
	case err != nil && strings.Contains(strings.ToLower(err.Error()), "connection refused"):
		return "controller_unavailable", "controller is unavailable at the configured PAC_URL; waiting for PAC to come back"
	case err != nil:
		return "transport_error", fmt.Sprintf("endpoint registration transport error: %v", err)
	case code >= 500:
		return "server_error", fmt.Sprintf("controller returned HTTP %d during endpoint registration", code)
	case code >= 400:
		if body != "" {
			return fmt.Sprintf("http_%d", code), fmt.Sprintf("endpoint registration rejected with HTTP %d: %s", code, body)
		}
		return fmt.Sprintf("http_%d", code), fmt.Sprintf("endpoint registration rejected with HTTP %d", code)
	default:
		return "unknown", "endpoint registration failed for an unknown reason"
	}
}

func registerWithRetry(ctx context.Context, c Client, reg map[string]any, name string, runnerEnabled bool) Runner {
	backoff := 5 * time.Second
	maxBackoff := 30 * time.Second
	state := registerAttemptState{}
	for {
		data, code, err := c.request(ctx, "POST", "/v1/endpoints/register", reg)
		if err == nil && code < 300 {
			var r Runner
			json.Unmarshal(data, &r)
			if r.ID == "" {
				fmt.Fprintln(os.Stderr, "register response did not include endpoint id")
			} else {
				if state.Attempts > 0 {
					fmt.Fprintf(os.Stderr, "endpoint registration recovered after %d attempt(s)\n", state.Attempts)
				}
				fmt.Printf("PAC endpoint %s registered as %s, version %s, runner enabled: %t\n", name, r.ID, version, runnerEnabled)
				return r
			}
		}
		key, msg := classifyRegisterFailure(err, code, data)
		if key != state.Key {
			state = registerAttemptState{Key: key, Attempts: 1}
			fmt.Fprintf(os.Stderr, "endpoint registration waiting: %s\n", msg)
		} else {
			state.Attempts++
			if state.Attempts == 2 || state.Attempts%12 == 0 {
				fmt.Fprintf(os.Stderr, "endpoint registration still waiting (%d attempts): %s\n", state.Attempts, msg)
			}
		}
		time.Sleep(backoff)
		if backoff < maxBackoff {
			backoff *= 2
			if backoff > maxBackoff {
				backoff = maxBackoff
			}
		}
	}
}

func main() {
	os.Args = append(os.Args[:1], applyEnvAssignments(os.Args[1:])...)
	base := strings.TrimRight(env("PAC_URL", defaultServerURL), "/")
	token := env("PAC_TOKEN", "")
	name := env("PAC_ENDPOINT_NAME", strings.TrimSpace(defaultEndpointName))
	if name == "" {
		h, _ := os.Hostname()
		name = h
	}
	if base == "" {
		fmt.Fprintln(os.Stderr, "PAC_URL is required")
		os.Exit(2)
	}
	runnerEnabledFallback := true
	switch strings.ToLower(strings.TrimSpace(defaultRunnerEnabled)) {
	case "", "1", "true", "yes", "on", "enabled":
		runnerEnabledFallback = true
	case "0", "false", "no", "off", "disabled":
		runnerEnabledFallback = false
	}
	runnerEnabled := envBool("PAC_RUNNER_ENABLED", runnerEnabledFallback)
	c := Client{base: base, token: token, http: newHTTPClient()}
	ctx := context.Background()
	labels := []string{"endpoint", runtime.GOOS, runtime.GOARCH}
	if runnerEnabled {
		labels = append(labels, "remote-execution")
	} else {
		labels = append(labels, "runner-disabled")
	}
	controllerWrapper := envBool("PAC_CONTROLLER_WRAPPER", false)
	metadata := map[string]any{"runner_version": version, "runner_embedded": true, "runner_enabled": runnerEnabled, "binary": binaryName, "os": runtime.GOOS, "arch": runtime.GOARCH, "secure_transport": "bearer-token optional-mtls", "self_update": true, "tool_bridge": true, "required_tools": requiredToolSummary(discoverEndpointTools()), "compiled_server_url": defaultServerURL, "controller_id": defaultControllerID, "update_channel": defaultUpdateChannel, "controller_wrapper": controllerWrapper}
	if controllerWrapper {
		labels = append(labels, "controller", "local", "PAC", "pi.dev")
		metadata["local_control_plane"] = true
		metadata["pi_dev_required"] = true
	}
	reg := map[string]any{"name": name, "labels": labels, "endpoint": "pac-endpoint://" + name, "allow_host_execution": runnerEnabled, "allow_container_execution": runnerEnabled, "agent_enabled": controllerWrapper, "metadata": metadata}
	r := registerWithRetry(ctx, c, reg, name, runnerEnabled)
	for {
		hbMetadata := map[string]any{"command_channel": map[string]any{"available": runnerEnabled, "mode": "controller-queued", "embedded": true}, "runner_enabled": runnerEnabled, "self_update": true, "tool_bridge": true, "required_tools": requiredToolSummary(discoverEndpointTools()), "compiled_server_url": defaultServerURL, "controller_id": defaultControllerID, "update_channel": defaultUpdateChannel, "controller_wrapper": controllerWrapper}
		if controllerWrapper {
			hbMetadata["local_control_plane"] = true
			hbMetadata["pi_dev_required"] = true
		}
		hb := map[string]any{"runner_id": r.ID, "status": "online", "version": version, "labels": reg["labels"], "capabilities": runtimeCapabilities(runnerEnabled), "metadata": hbMetadata}
		c.request(ctx, "POST", "/v1/endpoints/heartbeat", hb)
		if !runnerEnabled {
			time.Sleep(5 * time.Second)
			continue
		}
		data, code, err := c.request(ctx, "GET", "/v1/endpoints/"+r.ID+"/jobs/next", nil)
		if err == nil && code == 200 && strings.TrimSpace(string(data)) != "null" {
			var job Job
			if json.Unmarshal(data, &job) == nil && job.ID != "" {
				c.request(ctx, "POST", "/v1/runner-jobs/"+job.ID+"/log", map[string]any{"stream": "system", "message": "job started on " + binaryName + " " + version})
				exit, out, stderr := 1, "", ""
				if job.Command == "" {
					stderr = "job.command is empty"
				} else if stringMeta(job.Metadata, "operation") == "self_update" {
					exit, out, stderr = selfUpdate(job)
				} else if strings.TrimSpace(stringMeta(job.Metadata, "tool_name")) != "" {
					exit, out, stderr = runToolInvocation(job)
				} else {
					exit, out, stderr = runCommand(job)
				}
				status := "completed"
				if exit != 0 {
					status = "failed"
				}
				c.request(ctx, "POST", "/v1/runner-jobs/"+job.ID, map[string]any{"status": status, "output": out, "error": stderr, "exit_code": exit, "metadata": map[string]any{"endpoint_version": version}})
			}
		} else if err != nil && !errors.Is(err, context.Canceled) {
			fmt.Fprintln(os.Stderr, err)
		}
		time.Sleep(5 * time.Second)
	}
}
