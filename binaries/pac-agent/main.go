package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

var version = "dev"
var defaultServerURL = ""
var defaultControllerID = ""
var defaultUpdateChannel = "stable"

const binaryName = "pac-agent"

type Runner struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}
type Job struct {
	ID            string         `json:"id"`
	Prompt        string         `json:"prompt"`
	Command       string         `json:"command"`
	WorkspacePath string         `json:"workspace_path"`
	Metadata      map[string]any `json:"metadata"`
}
type Client struct {
	base, token string
	http        *http.Client
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

func env(k, d string) string {
	if v := strings.TrimSpace(os.Getenv(k)); v != "" {
		return v
	}
	return d
}
func httpClient() *http.Client {
	tr := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}}
	if ca := env("PAC_CA_FILE", ""); ca != "" {
		if pem, err := os.ReadFile(ca); err == nil {
			pool, _ := x509.SystemCertPool()
			if pool == nil {
				pool = x509.NewCertPool()
			}
			pool.AppendCertsFromPEM(pem)
			tr.TLSClientConfig.RootCAs = pool
		}
	}
	return &http.Client{Timeout: 60 * time.Second, Transport: tr}
}
func (c Client) req(ctx context.Context, method, path string, body any) ([]byte, int, error) {
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
	req.Header.Set("User-Agent", binaryName+"/"+version)
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
func sh(command, cwd string) (int, string, string) {
	shell := "/bin/sh"
	arg := "-lc"
	if runtime.GOOS == "windows" {
		shell = "cmd"
		arg = "/C"
	}
	cmd := exec.Command(shell, arg, command)
	cmd.Dir = cwd
	cmd.Env = append(os.Environ(), "PAC_WORKSPACE="+cwd, "PAC_AGENT_VERSION="+version)
	var out, er bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &er
	err := cmd.Run()
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
func workspace(job Job) string {
	root := strings.TrimSpace(job.WorkspacePath)
	if root == "" {
		root = env("PAC_WORKSPACE", filepath.Join(os.TempDir(), "pac-agent-workspace"))
	}
	abs, _ := filepath.Abs(root)
	_ = os.MkdirAll(abs, 0750)
	return abs
}

func main() {
	os.Args = append(os.Args[:1], applyEnvAssignments(os.Args[1:])...)
	base := strings.TrimRight(env("PAC_URL", defaultServerURL), "/")
	token := env("PAC_TOKEN", "")
	name := env("PAC_AGENT_NAME", "")
	if name == "" {
		h, _ := os.Hostname()
		name = h + "-agent"
	}
	if base == "" {
		fmt.Fprintln(os.Stderr, "PAC_URL is required (or compile with PAC_COMPILED_SERVER_URL)")
		os.Exit(2)
	}
	c := Client{base: base, token: token, http: httpClient()}
	ctx := context.Background()
	labels := []string{"pac-agent", runtime.GOOS, runtime.GOARCH}
	reg := map[string]any{"name": name, "labels": labels, "endpoint": "pac-agent://" + name, "allow_host_execution": true, "allow_container_execution": false, "agent_enabled": true, "metadata": map[string]any{"runner_version": version, "binary": binaryName, "os": runtime.GOOS, "arch": runtime.GOARCH, "workspace": env("PAC_WORKSPACE", "")}}
	data, code, err := c.req(ctx, "POST", "/v1/endpoints/register", reg)
	if err != nil || code >= 300 {
		fmt.Fprintf(os.Stderr, "register failed: %v %d %s\n", err, code, string(data))
		os.Exit(1)
	}
	var r Runner
	json.Unmarshal(data, &r)
	if r.ID == "" {
		fmt.Fprintln(os.Stderr, "register response missing endpoint id")
		os.Exit(1)
	}
	fmt.Printf("PAC agent registered as %s, version %s\n", r.ID, version)
	for {
		caps := map[string]any{"binary": binaryName, "version": version, "os": runtime.GOOS, "arch": runtime.GOARCH, "workspace": env("PAC_WORKSPACE", filepath.Join(os.TempDir(), "pac-agent-workspace")), "agent": map[string]any{"available": true, "mode": "command-worker"}}
		c.req(ctx, "POST", "/v1/endpoints/heartbeat", map[string]any{"runner_id": r.ID, "status": "online", "version": version, "labels": labels, "capabilities": caps, "metadata": map[string]any{"agent_enabled": true, "command_channel": map[string]any{"available": true, "mode": "controller-queued"}}})
		data, code, err := c.req(ctx, "GET", "/v1/endpoints/"+r.ID+"/jobs/next", nil)
		if err == nil && code == 200 && strings.TrimSpace(string(data)) != "null" {
			var job Job
			if json.Unmarshal(data, &job) == nil && job.ID != "" {
				c.req(ctx, "POST", "/v1/runner-jobs/"+job.ID+"/log", map[string]any{"stream": "system", "message": "agent job started"})
				exit, out, stderr := sh(job.Command, workspace(job))
				status := "completed"
				if exit != 0 {
					status = "failed"
				}
				c.req(ctx, "POST", "/v1/runner-jobs/"+job.ID, map[string]any{"status": status, "output": out, "error": stderr, "exit_code": exit, "metadata": map[string]any{"agent_version": version}})
			}
		}
		time.Sleep(5 * time.Second)
	}
}
