# pac-mcp

Small Go MCP stdio bridge for Zed and other MCP clients.

It does not run PAC locally. It forwards MCP tool calls to a PAC server API.

Example:

```json
{
  "context_servers": {
    "pac": {
      "command": "/path/to/pac-mcp-linux-amd64",
      "args": ["--base-url", "https://192.168.0.7"]
    }
  }
}
```
