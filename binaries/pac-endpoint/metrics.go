package main

import (
	"bufio"
	"os"
	"runtime"
	"strconv"
	"strings"
	"time"
)

func endpointMetrics(root string) map[string]any {
	metrics := map[string]any{
		"collected_at": time.Now().UTC().Format(time.RFC3339),
		"os":           runtime.GOOS,
		"arch":         runtime.GOARCH,
	}
	for key, value := range loadMetrics() {
		metrics[key] = value
	}
	if mem := memoryMetrics(); len(mem) > 0 {
		metrics["memory"] = mem
	}
	if disks := diskInventory(root); len(disks) > 0 {
		metrics["disks"] = disks
	}
	return metrics
}

func loadMetrics() map[string]any {
	out := map[string]any{}
	if runtime.GOOS != "linux" {
		return out
	}
	data, err := os.ReadFile("/proc/loadavg")
	if err != nil {
		return out
	}
	fields := strings.Fields(string(data))
	if len(fields) >= 3 {
		out["load_1m"] = parseFloat(fields[0])
		out["load_5m"] = parseFloat(fields[1])
		out["load_15m"] = parseFloat(fields[2])
	}
	return out
}

func memoryMetrics() map[string]any {
	out := map[string]any{}
	if runtime.GOOS != "linux" {
		return out
	}
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return out
	}
	defer f.Close()
	values := map[string]int64{}
	for scanner := bufio.NewScanner(f); scanner.Scan(); {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 2 {
			continue
		}
		key := strings.TrimSuffix(fields[0], ":")
		kb, err := strconv.ParseInt(fields[1], 10, 64)
		if err == nil {
			values[key] = kb * 1024
		}
	}
	total := values["MemTotal"]
	available := values["MemAvailable"]
	if total > 0 {
		out["total_bytes"] = total
		out["available_bytes"] = available
		out["used_bytes"] = total - available
		out["used_ratio"] = float64(total-available) / float64(total)
	}
	return out
}

func parseFloat(value string) float64 {
	parsed, _ := strconv.ParseFloat(strings.TrimSpace(value), 64)
	return parsed
}
