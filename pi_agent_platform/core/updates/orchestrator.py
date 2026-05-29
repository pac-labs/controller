from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pi_agent_platform.core.platform_home import pacp_path
from pi_agent_platform.updates import download_release_asset, fetch_latest_release_assets

PRIMARY_BINARIES = ("pac-endpoint", "pacctl")


def host_binary_target() -> str:
    system = platform.system().lower()
    goos = {"linux": "linux", "darwin": "darwin", "windows": "windows"}.get(system, system or "linux")
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        goarch = "amd64"
    elif machine in {"aarch64", "arm64"}:
        goarch = "arm64"
    elif machine.startswith("armv7") or machine == "arm":
        goarch = "arm"
    else:
        goarch = machine or "amd64"
    return f"{goos}/{goarch}"


def _stage(name: str, status: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"name": name, "status": status, "message": message}
    payload.update(extra)
    return payload


def _safe_key(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum() or ch in ("-", "_", ".", ":")) or "asset"


def _binary_cache_path(asset_name: str) -> Path:
    return pacp_path("updates", "release-assets", "binaries", Path(asset_name).name)


def _install_binary(src: Path, component: str) -> dict[str, Any]:
    ext = ".exe" if platform.system().lower() == "windows" else ""
    target = pacp_path("bin", f"{component}{ext}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".new")
    shutil.copy2(src, tmp)
    try:
        tmp.chmod(tmp.stat().st_mode | 0o111)
    except Exception:
        pass
    tmp.replace(target)
    return {"component": component, "path": str(target), "size": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def _load_binary_manifest(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = pacp_path("updates", "release-assets", "release_binaries_manifest", "RELEASE_BINARIES.json")
    result = download_release_asset("release_binaries_manifest", target)
    if not result.get("ok"):
        stages.append(_stage("release-binary-manifest", "failed", result.get("error") or "RELEASE_BINARIES.json could not be downloaded.", result=result))
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        stages.append(_stage("release-binary-manifest", "failed", f"RELEASE_BINARIES.json could not be parsed: {exc}", path=str(target)))
        return None
    if not isinstance(data, dict):
        stages.append(_stage("release-binary-manifest", "failed", "RELEASE_BINARIES.json did not contain an object.", path=str(target)))
        return None
    stages.append(_stage("release-binary-manifest", "ok", "Release binary manifest downloaded.", path=str(target), binary_count=len(data.get("binaries") or [])))
    return data


def _find_manifest_binary(manifest: dict[str, Any], component: str, target: str) -> dict[str, Any] | None:
    for item in manifest.get("binaries") or []:
        if not isinstance(item, dict):
            continue
        if item.get("project") == component and item.get("target") == target:
            return item
    return None


def _download_direct_binary(record: dict[str, Any], assets_payload: dict[str, Any]) -> dict[str, Any]:
    asset_name = str(record.get("asset_name") or record.get("download_name") or "").strip()
    if not asset_name:
        return {"ok": False, "status": "missing_asset_name", "message": "Binary manifest entry has no asset_name."}
    asset_key = f"binary:{asset_name}"
    target = _binary_cache_path(asset_name)
    result = download_release_asset(asset_key, target)
    if not result.get("ok"):
        return {"ok": False, "status": result.get("status") or "download_failed", "asset_key": asset_key, "asset_name": asset_name, "message": result.get("error") or "Direct binary asset download failed.", "result": result}
    expected = str(record.get("sha256") or "").strip().lower()
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if expected and actual != expected:
        return {"ok": False, "status": "checksum_mismatch", "asset_key": asset_key, "asset_name": asset_name, "path": str(target), "expected_sha256": expected, "actual_sha256": actual}
    try:
        target.chmod(target.stat().st_mode | 0o111)
    except Exception:
        pass
    return {"ok": True, "asset_key": asset_key, "asset_name": asset_name, "path": str(target), "sha256": actual, "size": target.stat().st_size}


def resolve_release_binaries(*, target: str | None = None, components: list[str] | None = None) -> dict[str, Any]:
    """Download and install the host pac-endpoint/pacctl binaries from GitHub release assets."""
    selected_target = target or host_binary_target()
    selected_components = components or list(PRIMARY_BINARIES)
    stages: list[dict[str, Any]] = []
    installed: list[dict[str, Any]] = []
    manifest = _load_binary_manifest(stages)
    assets = fetch_latest_release_assets()
    if not assets.get("ok"):
        stages.append(_stage("release-assets", "failed", assets.get("error") or "GitHub release assets could not be read.", result=assets))
    else:
        stages.append(_stage("release-assets", "ok", "GitHub release assets loaded.", release=assets.get("tag"), asset_count=len(assets.get("assets") or {})))
    if not manifest:
        return {"ok": False, "target": selected_target, "components": selected_components, "stages": stages, "installed": installed}
    for component in selected_components:
        record = _find_manifest_binary(manifest, component, selected_target)
        if not record:
            stages.append(_stage(f"binary:{component}", "failed", f"No {component} binary is published for {selected_target}.", component=component, target=selected_target))
            continue
        download = _download_direct_binary(record, assets)
        if not download.get("ok"):
            stages.append(_stage(f"binary:{component}", "failed", download.get("message") or "Binary download failed.", component=component, target=selected_target, download=download))
            continue
        install = _install_binary(Path(download["path"]), component)
        installed.append({**install, "target": selected_target, "asset_name": record.get("asset_name"), "component_version": record.get("component_version")})
        stages.append(_stage(f"binary:{component}", "ok", f"{component} installed from GitHub release asset.", component=component, target=selected_target, download=download, install=install))
    ok = len(installed) == len(selected_components)
    return {"ok": ok, "target": selected_target, "components": selected_components, "stages": stages, "installed": installed}


def write_agent_tool_instructions(*, version: str | None = None, binary_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh the controller-side instructions consumed by pi.dev/PAC agent contexts."""
    root = pacp_path("agent", "tool-instructions")
    root.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    tools = [
        {
            "name": "pacctl",
            "role": "PAC client and integration tool",
            "commands": [
                "pacctl api get /v1/version",
                "pacctl poll events",
                "pacctl provider send --file provider.json",
                "pacctl workspace status <workspace>",
                "pacctl workspace exec <workspace> --stream -- <command>",
                "pacctl workspace cancel <workspace> <command_id>",
                "pacctl mcp serve",
            ],
        },
        {
            "name": "pac-endpoint",
            "role": "PAC endpoint/workspace wrapper",
            "commands": [
                "pac-endpoint daemon",
                "pac-endpoint workspace run",
                "pac-endpoint workspace register",
                "pac-endpoint workspace status",
            ],
        },
    ]
    json_payload = {
        "schema": "pac.agent-tool-instructions.v1",
        "generated_at": generated_at,
        "pac_version": version,
        "tools": tools,
        "binary_resolution": binary_result or {},
        "notes": [
            "Use pacctl to communicate with PAC, providers, endpoints, workspaces, and MCP clients.",
            "Use pac-endpoint as the resident endpoint/workspace wrapper; workspace containers should run pac-endpoint workspace run.",
            "Do not assume binaries are bundled in PAC source zips; resolve them from GitHub Release assets or the local PAC bin cache.",
        ],
    }
    json_path = root / "PAC_TOOLS.json"
    md_path = root / "PAC_TOOLS.md"
    json_path.write_text(json.dumps(json_payload, indent=2) + "\n", encoding="utf-8")
    md_lines = [
        "# PAC tool instructions",
        "",
        f"Generated: {generated_at}",
        f"PAC version: {version or 'unknown'}",
        "",
        "PAC uses two installable binaries:",
        "",
        "- `pac-endpoint`: resident endpoint/workspace wrapper. It registers hosts/workspaces, forwards telemetry, receives PAC-routed commands, streams output, and keeps workspace containers online with `pac-endpoint workspace run`.",
        "- `pacctl`: client/integration utility. It talks to PAC, sends provider data, polls state/events, controls endpoints/workspaces through PAC, and serves MCP/editor integrations.",
        "",
        "Useful commands:",
    ]
    for tool in tools:
        md_lines.append(f"\n## {tool['name']}\n")
        md_lines.append(str(tool["role"]))
        for command in tool["commands"]:
            md_lines.append(f"- `{command}`")
    md_lines.extend([
        "",
        "Workspace routing model:",
        "",
        "```text",
        "pacctl -> PAC controller -> pac-endpoint workspace/endpoint agent -> command execution",
        "```",
        "",
    ])
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return {"ok": True, "generated_at": generated_at, "json_path": str(json_path), "markdown_path": str(md_path), "tool_count": len(tools)}


def run_update_orchestration(
    *,
    version: str | None = None,
    target: str | None = None,
    components: list[str] | None = None,
    rebuild_pi_dev: Callable[[], dict[str, Any]] | None = None,
    restart_pi_dev: Callable[[], dict[str, Any]] | None = None,
    refresh_metadata: Callable[[], Any] | None = None,
    verify_pi_dev: Callable[[], dict[str, Any]] | None = None,
    auto_rebuild_pi_dev: bool = False,
) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    binary_result = resolve_release_binaries(target=target, components=components)
    stages.extend(binary_result.get("stages") or [])
    instructions = write_agent_tool_instructions(version=version, binary_result=binary_result)
    stages.append(_stage("agent-tool-instructions", "ok" if instructions.get("ok") else "failed", "PAC/pi.dev tool instructions refreshed.", result=instructions))
    pi_dev_update: dict[str, Any] = {"ok": False, "status": "skipped", "message": "pi.dev rebuild skipped."}
    pi_dev_restart: dict[str, Any] = {"ok": False, "status": "skipped", "message": "pi.dev restart skipped."}
    if auto_rebuild_pi_dev and rebuild_pi_dev:
        pi_dev_update = rebuild_pi_dev()
        stages.append(_stage("pi-dev-runtime", "ok" if pi_dev_update.get("exit_code") == 0 or pi_dev_update.get("ok") else "failed", "pi.dev runtime refreshed.", result=pi_dev_update))
        if (pi_dev_update.get("exit_code") == 0 or pi_dev_update.get("ok")) and restart_pi_dev:
            pi_dev_restart = restart_pi_dev()
            stages.append(_stage("pi-dev-restart", "ok" if pi_dev_restart.get("ok") or pi_dev_restart.get("status") == "restarted" else "warn", "pi.dev runtime restart requested.", result=pi_dev_restart))
    if refresh_metadata:
        try:
            refreshed = refresh_metadata()
            stages.append(_stage("local-metadata", "ok", "Local endpoint/tool metadata refreshed.", result={"ok": True, "value": str(type(refreshed).__name__)}))
        except Exception as exc:
            stages.append(_stage("local-metadata", "warn", f"Local endpoint/tool metadata refresh failed: {exc}"))
    pi_dev_check = verify_pi_dev() if verify_pi_dev else {"ok": False, "status": "skipped", "message": "pi.dev verification skipped."}
    stages.append(_stage("pi-dev-check", "ok" if pi_dev_check.get("ok") else "warn", pi_dev_check.get("message") or "pi.dev verification completed.", result=pi_dev_check))
    ok = bool(binary_result.get("ok")) and bool(instructions.get("ok"))
    return {
        "ok": ok,
        "status": "environment_ready" if ok else "environment_needs_attention",
        "version": version,
        "target": binary_result.get("target"),
        "stages": stages,
        "binaries": binary_result,
        "agent_tool_instructions": instructions,
        "pi_dev_update": pi_dev_update,
        "pi_dev_restart": pi_dev_restart,
        "pi_dev_check": pi_dev_check,
    }


def plan_update_orchestration(*, target: str | None = None, components: list[str] | None = None) -> dict[str, Any]:
    selected_target = target or host_binary_target()
    selected_components = components or list(PRIMARY_BINARIES)
    return {
        "ok": True,
        "target": selected_target,
        "components": selected_components,
        "stages": [
            _stage("release-binary-manifest", "planned", "Download RELEASE_BINARIES.json from the GitHub Release."),
            *[_stage(f"binary:{component}", "planned", f"Download and install {component} for {selected_target}.", component=component, target=selected_target) for component in selected_components],
            _stage("agent-tool-instructions", "planned", "Regenerate PAC/pi.dev tool instructions."),
            _stage("pi-dev-runtime", "planned", "Rebuild/restart pi.dev runtime when configured."),
            _stage("local-metadata", "planned", "Refresh local endpoint/tool metadata."),
            _stage("pi-dev-check", "planned", "Verify pi.dev runtime after update."),
        ],
    }
