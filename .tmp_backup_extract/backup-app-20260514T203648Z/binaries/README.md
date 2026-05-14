# PAC binary sources

Controller bundle: 1.0.55

Each binary source folder has its own `VERSION`. Build artifacts use that source version, not the PAC controller version.

Buildable folders:

- `pac-endpoint/` builds the remote execution endpoint binary.
- `pac-endpoint-runner/` builds the endpoint runner binary used for endpoint downloads.
- `pac-agent/` builds the PAC agent worker binary.
- `zed-binary/` builds the Zed connector binary.

Select one of these folders in the Source Library and use **Build binary**. The build runs from the folder root and produces OS/architecture-specific downloads.
