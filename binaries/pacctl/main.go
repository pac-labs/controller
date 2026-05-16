package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"runtime"
	"sort"
	"strings"
	"time"
)

var version = "dev"
var defaultServerURL = ""

type client struct {
	base string
	http *http.Client
}

func env(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func newHTTPClient() *http.Client {
	tr := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}}
	if caFile := strings.TrimSpace(os.Getenv("PAC_CA_FILE")); caFile != "" {
		if pem, err := os.ReadFile(caFile); err == nil {
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

func newClient() (*client, error) {
	base := strings.TrimRight(env("PAC_URL", defaultServerURL), "/")
	if base == "" {
		return nil, errors.New("PAC_URL is required")
	}
	return &client{base: base, http: newHTTPClient()}, nil
}

func (c *client) requestJSON(ctx context.Context, method, path string, body any) (map[string]any, error) {
	var reader io.Reader
	if body != nil {
		buf, _ := json.Marshal(body)
		reader = bytes.NewReader(buf)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, reader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "pacctl/"+version+" "+runtime.GOOS+"/"+runtime.GOARCH)
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if token := strings.TrimSpace(os.Getenv("PAC_TOKEN")); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if runnerID := strings.TrimSpace(os.Getenv("PAC_RUNNER_ID")); runnerID != "" {
		req.Header.Set("X-PAC-Runner-ID", runnerID)
	}
	if runnerKey := strings.TrimSpace(os.Getenv("PAC_RUNNER_KEY")); runnerKey != "" {
		req.Header.Set("X-PAC-Runner-Key", runnerKey)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(data)))
	}
	if len(bytes.TrimSpace(data)) == 0 {
		return map[string]any{}, nil
	}
	var payload map[string]any
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	return payload, nil
}

func printJSON(value any) error {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(value)
}

func printValueOnly(value any) {
	switch typed := value.(type) {
	case string:
		fmt.Println(typed)
	default:
		buf, _ := json.Marshal(typed)
		fmt.Println(string(buf))
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, `pacctl %s

Usage:
  pacctl version
  pacctl config get
  pacctl context resolve [--name NAME | --path PATH] [--secrets]
  pacctl secret get SECRET_ID [--value-only]
  pacctl variable list
  pacctl variable get VARIABLE_ID [--value-only]
  pacctl ram list
  pacctl ram get <profile|user|workspace> KEY [--content-only]
  pacctl ram bundle [--profile NAME] [--user NAME] [--workspace NAME] [--content-only]
  pacctl ram search QUERY [--kind profile|user|workspace] [--limit N]

Environment:
  PAC_URL         Controller base URL, for example https://192.168.0.7:8443
  PAC_TOKEN       Admin bearer token
  PAC_RUNNER_ID   Endpoint identity for scoped retrieval
  PAC_RUNNER_KEY  Endpoint shared key for scoped retrieval
  PAC_CA_FILE     Optional controller CA bundle
`, version)
}

func contains(args []string, wanted string) bool {
	for _, arg := range args {
		if arg == wanted {
			return true
		}
	}
	return false
}

func flagValue(args []string, name string) string {
	for i := 0; i < len(args); i++ {
		if args[i] == name && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}

func flagIntValue(args []string, name string, fallback int) int {
	raw := strings.TrimSpace(flagValue(args, name))
	if raw == "" {
		return fallback
	}
	var value int
	if _, err := fmt.Sscanf(raw, "%d", &value); err != nil || value <= 0 {
		return fallback
	}
	return value
}

func printRAMContentOnly(payload map[string]any) {
	printValueOnly(payload["content"])
}

func printRAMBundleOnly(payload map[string]any) {
	items, _ := payload["items"].([]any)
	first := true
	for _, item := range items {
		record, _ := item.(map[string]any)
		if record == nil {
			continue
		}
		if !first {
			fmt.Println()
		}
		first = false
		fmt.Printf("=== %s:%s ===\n", fmt.Sprint(record["kind"]), fmt.Sprint(record["key"]))
		printValueOnly(record["content"])
	}
}

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		usage()
		os.Exit(2)
	}
	if args[0] == "version" {
		fmt.Printf("pacctl %s\n", version)
		return
	}
	c, err := newClient()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	ctx := context.Background()
	switch args[0] {
	case "config":
		if len(args) < 2 || args[1] != "get" {
			usage()
			os.Exit(2)
		}
		payload, err := c.requestJSON(ctx, "GET", "/v1/ide/config", nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		_ = printJSON(payload)
	case "context":
		if len(args) < 2 || args[1] != "resolve" {
			usage()
			os.Exit(2)
		}
		values := url.Values{}
		if name := flagValue(args, "--name"); name != "" {
			values.Set("name", name)
		}
		if path := flagValue(args, "--path"); path != "" {
			values.Set("path", path)
		}
		values.Set("include_secrets", fmt.Sprintf("%t", contains(args, "--secrets")))
		payload, err := c.requestJSON(ctx, "GET", "/v1/source-contexts/resolve?"+values.Encode(), nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		_ = printJSON(payload)
	case "secret":
		if len(args) < 3 || args[1] != "get" {
			usage()
			os.Exit(2)
		}
		payload, err := c.requestJSON(ctx, "GET", "/v1/secrets/"+url.PathEscape(args[2]), nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if contains(args, "--value-only") {
			printValueOnly(payload["value"])
		} else {
			_ = printJSON(payload)
		}
	case "variable":
		if len(args) < 2 {
			usage()
			os.Exit(2)
		}
		switch args[1] {
		case "list":
			payload, err := c.requestJSON(ctx, "GET", "/v1/source-variables", nil)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			vars, _ := payload["variables"].([]any)
			ids := []string{}
			for _, item := range vars {
				record, _ := item.(map[string]any)
				if record != nil {
					ids = append(ids, fmt.Sprint(record["id"]))
				}
			}
			sort.Strings(ids)
			for _, id := range ids {
				fmt.Println(id)
			}
		case "get":
			if len(args) < 3 {
				usage()
				os.Exit(2)
			}
			payload, err := c.requestJSON(ctx, "GET", "/v1/source-variables/"+url.PathEscape(args[2]), nil)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if contains(args, "--value-only") {
				printValueOnly(payload["value"])
			} else {
				_ = printJSON(payload)
			}
		default:
			usage()
			os.Exit(2)
		}
	case "ram":
		if len(args) < 2 {
			usage()
			os.Exit(2)
		}
		switch args[1] {
		case "list":
			payload, err := c.requestJSON(ctx, "GET", "/v1/pac-ram/list", nil)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			_ = printJSON(payload)
		case "get":
			if len(args) < 4 {
				usage()
				os.Exit(2)
			}
			kind := args[2]
			key := args[3]
			payload, err := c.requestJSON(ctx, "GET", "/v1/pac-ram/"+url.PathEscape(kind)+"/"+url.PathEscape(key), nil)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if contains(args, "--content-only") {
				printRAMContentOnly(payload)
			} else {
				_ = printJSON(payload)
			}
		case "bundle":
			values := url.Values{}
			if profile := flagValue(args, "--profile"); profile != "" {
				values.Set("profile", profile)
			}
			if user := flagValue(args, "--user"); user != "" {
				values.Set("user", user)
			}
			if workspace := flagValue(args, "--workspace"); workspace != "" {
				values.Set("workspace", workspace)
			}
			payload, err := c.requestJSON(ctx, "GET", "/v1/pac-ram/bundle?"+values.Encode(), nil)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if contains(args, "--content-only") {
				printRAMBundleOnly(payload)
			} else {
				_ = printJSON(payload)
			}
		case "search":
			if len(args) < 3 {
				usage()
				os.Exit(2)
			}
			values := url.Values{}
			values.Set("q", args[2])
			if kind := flagValue(args, "--kind"); kind != "" {
				values.Set("kind", kind)
			}
			values.Set("limit", fmt.Sprintf("%d", flagIntValue(args, "--limit", 10)))
			payload, err := c.requestJSON(ctx, "GET", "/v1/pac-ram/search?"+values.Encode(), nil)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			_ = printJSON(payload)
		default:
			usage()
			os.Exit(2)
		}
	default:
		usage()
		os.Exit(2)
	}
}
