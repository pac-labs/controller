package main

import (
	"bufio"
	"bytes"
	"fmt"
	"net"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
)

func endpointInventory(root string) map[string]any {
	hostname, _ := os.Hostname()
	return map[string]any{
		"hostname": hostname,
		"os":       runtime.GOOS,
		"arch":     runtime.GOARCH,
		"kernel":   kernelVersion(),
		"cpu":      cpuInventory(),
		"memory":   memoryInventory(),
		"disks":    diskInventory(root),
		"network":  networkInventory(),
		"tools":    discoverEndpointTools(),
	}
}

func kernelVersion() string {
	if runtime.GOOS == "windows" {
		return commandLine("cmd.exe", "/C", "ver")
	}
	return commandLine("uname", "-sr")
}

func commandLine(name string, args ...string) string {
	cmd := exec.Command(name, args...)
	var out bytes.Buffer
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		return ""
	}
	return strings.TrimSpace(out.String())
}

func cpuInventory() map[string]any {
	info := map[string]any{"logical_cores": runtime.NumCPU()}
	if runtime.GOOS == "linux" {
		if f, err := os.Open("/proc/cpuinfo"); err == nil {
			defer f.Close()
			models := map[string]bool{}
			for scanner := bufio.NewScanner(f); scanner.Scan(); {
				line := scanner.Text()
				if strings.HasPrefix(line, "model name") {
					parts := strings.SplitN(line, ":", 2)
					if len(parts) == 2 {
						models[strings.TrimSpace(parts[1])] = true
					}
				}
			}
			if len(models) == 1 {
				for model := range models {
					info["model"] = model
				}
			} else if len(models) > 1 {
				list := make([]string, 0, len(models))
				for model := range models {
					list = append(list, model)
				}
				info["models"] = list
			}
		}
	}
	if runtime.GOOS == "darwin" {
		if model := commandLine("sysctl", "-n", "machdep.cpu.brand_string"); model != "" {
			info["model"] = model
		}
	}
	return info
}

func memoryInventory() map[string]any {
	info := map[string]any{}
	if runtime.GOOS == "linux" {
		if f, err := os.Open("/proc/meminfo"); err == nil {
			defer f.Close()
			for scanner := bufio.NewScanner(f); scanner.Scan(); {
				line := scanner.Text()
				if strings.HasPrefix(line, "MemTotal:") {
					fields := strings.Fields(line)
					if len(fields) >= 2 {
						if kb, err := strconv.ParseInt(fields[1], 10, 64); err == nil {
							info["total_bytes"] = kb * 1024
						}
					}
					break
				}
			}
		}
	}
	if runtime.GOOS == "darwin" {
		if value := commandLine("sysctl", "-n", "hw.memsize"); value != "" {
			if bytes, err := strconv.ParseInt(strings.TrimSpace(value), 10, 64); err == nil {
				info["total_bytes"] = bytes
			}
		}
	}
	return info
}

func diskInventory(root string) []map[string]any {
	items := []map[string]any{}
	if runtime.GOOS == "windows" {
		return items
	}
	path := root
	if path == "" {
		path = "/"
	}
	cmd := exec.Command("df", "-kP", path)
	out, err := cmd.Output()
	if err != nil {
		return items
	}
	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	for _, line := range lines[1:] {
		fields := strings.Fields(line)
		if len(fields) < 6 {
			continue
		}
		sizeKB, _ := strconv.ParseInt(fields[1], 10, 64)
		usedKB, _ := strconv.ParseInt(fields[2], 10, 64)
		availKB, _ := strconv.ParseInt(fields[3], 10, 64)
		items = append(items, map[string]any{
			"filesystem":      fields[0],
			"mount":           fields[5],
			"size_bytes":      sizeKB * 1024,
			"used_bytes":      usedKB * 1024,
			"available_bytes": availKB * 1024,
		})
	}
	return items
}

func networkInventory() []map[string]any {
	items := []map[string]any{}
	interfaces, err := net.Interfaces()
	if err != nil {
		return items
	}
	for _, iface := range interfaces {
		addresses := []string{}
		if addrs, err := iface.Addrs(); err == nil {
			for _, addr := range addrs {
				addresses = append(addresses, addr.String())
			}
		}
		items = append(items, map[string]any{
			"name":      iface.Name,
			"mac":       iface.HardwareAddr.String(),
			"flags":     fmt.Sprint(iface.Flags),
			"addresses": addresses,
		})
	}
	return items
}
