# GitHub release binary artifacts without source zip bundling

PAC source and update zips should stay source-focused. They must not carry compiled endpoint or wrapper binaries.

## Release contract

GitHub Actions performs binary compilation before generating release metadata:

1. `scripts/compile-release-binaries.py` builds each Go binary component under `binaries/*`.
2. The compiled outputs are written under `dist/release-binaries/`.
3. `dist/pac-binaries.zip` is published as a GitHub Release asset.
4. `dist/RELEASE_BINARIES.json` is also published as a small manifest asset for UI/runtime inspection.
5. `dist/pac-full.zip` and `dist/pac-patch.zip` are validated to ensure they do not contain `release-binaries/` entries.

## Runtime resolution order

When PAC needs its local wrapper binary, it resolves it in this order:

1. Existing installed wrapper binary.
2. Existing locally built source artifact under the PAC source-build cache.
3. GitHub Release `pac-binaries.zip`, extracted only for the current host target.
4. Internal local build from `binaries/<component>` source.

This keeps webUI update packages small and avoids stale bundled binaries while preserving an offline-capable fallback when Go tooling is available locally.

## Versioning rule

PAC controller versions and component versions are independent. The binary artifact manifest records each component version from that component's own `VERSION` or `pac-component.json`; PAC releases do not force unchanged components to bump version.

## Direct installer helper

Controller installs now include `scripts/install-pac-binary.sh` for direct host-side installation of release binaries without bundling them in source zips.

Examples:

```sh
scripts/install-pac-binary.sh pacctl
scripts/install-pac-binary.sh pac-endpoint
scripts/install-pac-binary.sh pac-endpoint linux/arm64
```

The helper resolves the latest GitHub Release for `pac-labs/controller`, downloads the direct asset matching the host OS/architecture, and installs it into `$HOME/.local/bin` unless `PAC_BIN_DIR` is set.
