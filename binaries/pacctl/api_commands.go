package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

func (c *client) requestAny(ctx context.Context, method, path string, body any) (any, error) {
	var reader io.Reader
	if body != nil {
		buf, _ := json.Marshal(body)
		reader = bytes.NewReader(buf)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, reader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "pacctl/"+version)
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if token := strings.TrimSpace(os.Getenv("PAC_TOKEN")); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
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
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) == 0 {
		return map[string]any{"ok": true}, nil
	}
	var payload any
	if err := json.Unmarshal(trimmed, &payload); err != nil {
		return string(trimmed), nil
	}
	return payload, nil
}

func (c *client) requestStream(ctx context.Context, path string) (io.ReadCloser, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.base+path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "pacctl/"+version)
	req.Header.Set("Accept", "application/x-ndjson")
	if token := strings.TrimSpace(os.Getenv("PAC_TOKEN")); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 300 {
		defer resp.Body.Close()
		data, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(data)))
	}
	return resp.Body, nil
}

func handleAPI(ctx context.Context, c *client, args []string) int {
	if len(args) < 3 {
		usage()
		return 2
	}
	method := strings.ToUpper(args[1])
	path := args[2]
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	var body any
	if file := flagValue(args, "--file"); file != "" {
		payload, err := readJSONFile(file)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		body = payload
	}
	payload, err := c.requestAny(ctx, method, path, body)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	_ = printJSON(payload)
	return 0
}

func handleProvider(ctx context.Context, c *client, args []string) int {
	if len(args) < 2 {
		usage()
		return 2
	}
	switch args[1] {
	case "send", "register", "update":
		file := flagValue(args, "--file")
		if file == "" && len(args) > 2 {
			file = args[2]
		}
		if file == "" {
			fmt.Fprintln(os.Stderr, "provider payload file is required")
			return 2
		}
		payload, err := readJSONFile(file)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		result, err := c.requestAny(ctx, "POST", "/v1/providers", payload)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		_ = printJSON(result)
		return 0
	case "list":
		result, err := c.requestAny(ctx, "GET", "/v1/providers", nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		_ = printJSON(result)
		return 0
	default:
		usage()
		return 2
	}
}

func handlePoll(ctx context.Context, c *client, args []string) int {
	kind := "events"
	if len(args) > 1 {
		kind = args[1]
	}
	limit := flagIntValue(args, "--limit", 25)
	path := "/v1/events?limit=" + url.QueryEscape(fmt.Sprintf("%d", limit))
	switch kind {
	case "events":
		path = "/v1/events?limit=" + url.QueryEscape(fmt.Sprintf("%d", limit))
	case "endpoints":
		path = "/v1/endpoints"
	case "workspaces":
		path = "/v1/workspaces"
	default:
		fmt.Fprintln(os.Stderr, "unknown poll kind: "+kind)
		return 2
	}
	payload, err := c.requestAny(ctx, "GET", path, nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	_ = printJSON(payload)
	return 0
}

func handleWorkspace(ctx context.Context, c *client, args []string) int {
	if len(args) < 2 {
		usage()
		return 2
	}
	switch args[1] {
	case "status":
		if len(args) < 3 {
			usage()
			return 2
		}
		payload, err := c.requestAny(ctx, "GET", "/v1/workspaces/"+url.PathEscape(args[2]), nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		_ = printJSON(payload)
		return 0
	case "exec":
		return handleWorkspaceExec(ctx, c, args)
	case "cancel", "interrupt":
		return handleWorkspaceCancel(ctx, c, args)
	default:
		usage()
		return 2
	}
}

func handleWorkspaceCancel(ctx context.Context, c *client, args []string) int {
	if len(args) < 4 {
		usage()
		return 2
	}
	workspaceID := args[2]
	commandID := args[3]
	body := map[string]any{
		"reason": flagValue(args, "--reason"),
		"force":  contains(args, "--force"),
	}
	result, err := c.requestAny(ctx, "POST", "/v1/workspaces/"+url.PathEscape(workspaceID)+"/commands/"+url.PathEscape(commandID)+"/cancel", body)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	_ = printJSON(result)
	return 0
}

func handleWorkspaceExec(ctx context.Context, c *client, args []string) int {
	if len(args) < 4 {
		usage()
		return 2
	}
	workspaceID := args[2]
	commandArgs, wait, stream, timeout := parseWorkspaceExecArgs(args[3:])
	if len(commandArgs) == 0 {
		fmt.Fprintln(os.Stderr, "workspace command is required")
		return 2
	}
	body := map[string]any{"command": strings.Join(commandArgs, " "), "wait": wait}
	payload, err := c.requestAny(ctx, "POST", "/v1/workspaces/"+url.PathEscape(workspaceID)+"/commands", body)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if !wait && !stream {
		_ = printJSON(payload)
		return 0
	}
	commandID := commandIDFromPayload(payload)
	if commandID == "" {
		_ = printJSON(payload)
		return 1
	}
	if stream {
		return streamWorkspaceCommand(ctx, c, workspaceID, commandID, timeout)
	}
	return waitForWorkspaceCommand(ctx, c, workspaceID, commandID, timeout)
}

func parseWorkspaceExecArgs(args []string) ([]string, bool, bool, time.Duration) {
	wait := false
	stream := false
	timeout := 120 * time.Second
	command := []string{}
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch arg {
		case "--":
			command = append(command, args[i+1:]...)
			return command, wait, stream, timeout
		case "--wait":
			wait = true
		case "--stream":
			stream = true
			wait = true
		case "--timeout":
			if i+1 < len(args) {
				if seconds, err := strconv.Atoi(args[i+1]); err == nil && seconds > 0 {
					timeout = time.Duration(seconds) * time.Second
				}
				i++
			}
		default:
			command = append(command, args[i:]...)
			return command, wait, stream, timeout
		}
	}
	return command, wait, stream, timeout
}

func commandIDFromPayload(payload any) string {
	root, _ := payload.(map[string]any)
	if root == nil {
		return ""
	}
	command, _ := root["command"].(map[string]any)
	if command == nil {
		return ""
	}
	return strings.TrimSpace(fmt.Sprint(command["id"]))
}

func cancelWorkspaceCommand(ctx context.Context, c *client, workspaceID, commandID, reason string) {
	body := map[string]any{"reason": reason, "force": false}
	_, _ = c.requestAny(ctx, "POST", "/v1/workspaces/"+url.PathEscape(workspaceID)+"/commands/"+url.PathEscape(commandID)+"/cancel", body)
}

func streamWorkspaceCommand(ctx context.Context, c *client, workspaceID, commandID string, timeout time.Duration) int {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	body, err := c.requestStream(ctx, "/v1/workspaces/"+url.PathEscape(workspaceID)+"/commands/"+url.PathEscape(commandID)+"/stream")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	defer body.Close()
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	exitCode := 0
	statusSeen := false
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var event map[string]any
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			fmt.Fprintln(os.Stderr, line)
			continue
		}
		if fmt.Sprint(event["type"]) == "status" {
			statusSeen = true
			if raw := fmt.Sprint(event["exit_code"]); raw != "" && raw != "<nil>" {
				if parsed, err := strconv.Atoi(raw); err == nil {
					exitCode = parsed
				}
			}
			continue
		}
		stream := fmt.Sprint(event["stream"])
		data := fmt.Sprint(event["data"])
		switch stream {
		case "stdout":
			fmt.Fprint(os.Stdout, data)
		case "stderr":
			fmt.Fprint(os.Stderr, data)
		default:
			if data != "" && data != "<nil>" {
				fmt.Fprint(os.Stderr, data)
			}
		}
	}
	if err := scanner.Err(); err != nil {
		if ctx.Err() != nil {
			cancelWorkspaceCommand(context.Background(), c, workspaceID, commandID, "pacctl stream timeout or cancellation")
		}
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if !statusSeen {
		return waitForWorkspaceCommand(context.Background(), c, workspaceID, commandID, 5*time.Second)
	}
	return exitCode
}

func waitForWorkspaceCommand(ctx context.Context, c *client, workspaceID, commandID string, timeout time.Duration) int {
	deadline := time.Now().Add(timeout)
	var lastStatus string
	for {
		payload, err := c.requestAny(ctx, "GET", "/v1/workspaces/"+url.PathEscape(workspaceID)+"/commands/"+url.PathEscape(commandID), nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		command := commandFromPayload(payload)
		status := strings.TrimSpace(fmt.Sprint(command["status"]))
		if status != "" && status != lastStatus {
			lastStatus = status
			fmt.Fprintf(os.Stderr, "workspace command %s: %s\n", commandID, status)
		}
		if status == "completed" || status == "failed" || status == "interrupted" {
			if output := fmt.Sprint(command["output"]); output != "" && output != "<nil>" {
				fmt.Print(output)
				if !strings.HasSuffix(output, "\n") {
					fmt.Println()
				}
			}
			if errText := fmt.Sprint(command["error"]); errText != "" && errText != "<nil>" {
				fmt.Fprint(os.Stderr, errText)
				if !strings.HasSuffix(errText, "\n") {
					fmt.Fprintln(os.Stderr)
				}
			}
			if exitRaw := fmt.Sprint(command["exit_code"]); exitRaw != "" && exitRaw != "<nil>" {
				if exitCode, err := strconv.Atoi(exitRaw); err == nil {
					return exitCode
				}
			}
			if status == "completed" {
				return 0
			}
			return 1
		}
		if time.Now().After(deadline) {
			cancelWorkspaceCommand(context.Background(), c, workspaceID, commandID, "pacctl wait timeout")
			fmt.Fprintf(os.Stderr, "timed out waiting for workspace command %s; interrupt requested\n", commandID)
			return 124
		}
		sleepForPollInterval()
	}
}

func commandFromPayload(payload any) map[string]any {
	root, _ := payload.(map[string]any)
	if root == nil {
		return map[string]any{}
	}
	command, _ := root["command"].(map[string]any)
	if command == nil {
		return map[string]any{}
	}
	return command
}

func readJSONFile(path string) (any, error) {
	if path == "-" {
		var payload any
		data, _ := io.ReadAll(os.Stdin)
		return payload, json.Unmarshal(data, &payload)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var payload any
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	return payload, nil
}

func sleepForPollInterval() {
	time.Sleep(1 * time.Second)
}
