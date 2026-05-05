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
	"strings"
	"time"
)

var version = "dev"

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

type Client struct {
	base, token string
	http        *http.Client
}

func env(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
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
		root = env("PAC_WORKSPACE", filepath.Join(os.TempDir(), "pac-endpoint-workspace"))
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

func runtimeCapabilities() map[string]any {
	caps := map[string]any{"os": runtime.GOOS, "arch": runtime.GOARCH, "version": version, "binary": binaryName, "workspace": env("PAC_WORKSPACE", filepath.Join(os.TempDir(), "pac-endpoint-workspace"))}
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

func main() {
	base := strings.TrimRight(env("PAC_URL", ""), "/")
	token := env("PAC_TOKEN", "")
	name := env("PAC_ENDPOINT_NAME", "")
	if name == "" {
		h, _ := os.Hostname()
		name = h
	}
	if base == "" {
		fmt.Fprintln(os.Stderr, "PAC_URL is required")
		os.Exit(2)
	}
	c := Client{base: base, token: token, http: newHTTPClient()}
	ctx := context.Background()
	reg := map[string]any{"name": name, "labels": []string{"remote-execution", runtime.GOOS, runtime.GOARCH}, "endpoint": "pac-endpoint://" + name, "allow_host_execution": true, "allow_container_execution": true, "agent_enabled": false, "metadata": map[string]any{"runner_version": version, "binary": binaryName, "os": runtime.GOOS, "arch": runtime.GOARCH, "secure_transport": "bearer-token optional-mtls", "self_update": true}}
	data, code, err := c.request(ctx, "POST", "/v1/endpoints/register", reg)
	if err != nil || code >= 300 {
		fmt.Fprintf(os.Stderr, "register failed: %v %d %s\n", err, code, string(data))
		os.Exit(1)
	}
	var r Runner
	json.Unmarshal(data, &r)
	if r.ID == "" {
		fmt.Fprintln(os.Stderr, "register response did not include endpoint id")
		os.Exit(1)
	}
	fmt.Printf("PAC endpoint %s registered as %s, version %s\n", name, r.ID, version)
	for {
		hb := map[string]any{"runner_id": r.ID, "status": "online", "version": version, "labels": reg["labels"], "capabilities": runtimeCapabilities(), "metadata": map[string]any{"command_channel": map[string]any{"available": true, "mode": "controller-queued"}, "self_update": true}}
		c.request(ctx, "POST", "/v1/endpoints/heartbeat", hb)
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
