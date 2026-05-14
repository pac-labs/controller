# PAC full restore package

This package is intended for the case where `~/.pacp/config` and `~/.pacp/state.db` still exist, but the application source under `~/.pacp/app` was deleted or damaged.

## Restore / reinstall

```bash
unzip pac-full-restore-stage18.zip
cd pac-full-restore
./install.sh
```

The installer copies this package into `~/.pacp/app`, creates/updates the Python virtualenv, and starts the `pacp` service.

It preserves existing user state:

- `~/.pacp/config/config.yaml`
- `~/.pacp/state.db`
- `~/.pacp/artifacts/`
- `~/.pacp/workspaces/`
- `~/.pacp/sessions/`
- `~/.pacp/logs/`

To override the home directory:

```bash
PACP_HOME=/some/path ./install.sh
```

Default URL after install:

```text
http://localhost:8080
```

Service commands:

```bash
systemctl --user status pacp
systemctl --user restart pacp
systemctl --user stop pacp
```

If installed as root:

```bash
sudo systemctl status pacp
sudo systemctl restart pacp
sudo systemctl stop pacp
```
