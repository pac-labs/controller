# PAC feature update packs

Feature update packs add source-library content without replacing the PAC base product.

A pack is a `.zip` file containing one or more folders under these roots:

- `plugins/`
- `containers/`
- `binaries/`
- `scripts/`
- `docs/`

Recommended layout:

```text
plugins/my-plugin/VERSION
plugins/my-plugin/README.md
plugins/my-plugin/scripts/example.py
containers/my-container/VERSION
containers/my-container/Containerfile
binaries/my-binary/VERSION
binaries/my-binary/go.mod
binaries/my-binary/main.go
```

The Web UI previews every top-level feature folder and shows the installed version and incoming version before applying the pack. If a component does not include its own `VERSION`, PAC uses the zip root `VERSION` or the current controller version.

Feature updates are additive. Files present in the zip are copied into the source library. Existing files with the same path are replaced, but files omitted from the zip are not deleted.

PAC blocks feature update inspection and apply while container or binary builds are active. The event panel shows the pending state so sources are not changed under an active build.
