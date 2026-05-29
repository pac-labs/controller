from __future__ import annotations

from shlex import split as shlex_split
from typing import Any


SESSION_SLASH_COMMANDS: dict[str, dict[str, str]] = {
    "command": {
        "kind": "tool",
        "label": "/command <tool> [args]",
        "description": "Run a registered endpoint tool on the session workspace.",
    },
    "rg": {
        "kind": "tool",
        "tool": "rg",
        "label": "/rg <pattern> [path]",
        "description": "Run ripgrep in the session workspace.",
    },
    "fd": {
        "kind": "tool",
        "tool": "fd",
        "label": "/fd <pattern>",
        "description": "Find files in the session workspace.",
    },
    "jq": {
        "kind": "tool",
        "tool": "jq",
        "label": "/jq <filter>",
        "description": "Run jq in the session workspace.",
    },
    "git": {
        "kind": "tool",
        "tool": "git",
        "label": "/git <args>",
        "description": "Run git in the session workspace.",
    },
    "delta": {
        "kind": "tool",
        "tool": "delta",
        "label": "/delta [args]",
        "description": "Render diffs with delta.",
    },
    "bat": {
        "kind": "tool",
        "tool": "bat",
        "label": "/bat <file>",
        "description": "Preview a file with bat or batcat.",
    },
    "bad": {
        "kind": "tool",
        "tool": "bat",
        "label": "/bad <file>",
        "description": "Typo alias for /bat.",
    },
    "just": {
        "kind": "tool",
        "tool": "just",
        "label": "/just <recipe>",
        "description": "Run a just recipe in the session workspace.",
    },
    "press": {
        "kind": "tool",
        "tool": "printing_press",
        "label": "/press [args or path]",
        "description": "Run the Printing Press CLI in the session workspace.",
    },
    "plan": {
        "kind": "session",
        "label": "/plan <request>",
        "description": "Generate a PAC execution plan for the current request before acting.",
    },
    "compact": {
        "kind": "session",
        "label": "/compact",
        "description": "Compact the session context/history before the next model turn.",
    },
    "model": {
        "kind": "session",
        "label": "/model [model|provider:model] [--fallback=a,b]",
        "description": "Show or switch the active model for this session, with capability checks and fallback chain refresh.",
    },
    "subagent": {
        "kind": "pi.dev",
        "label": "/subagent <instruction>",
        "description": "Create a scoped pi.dev-backed subagent task for one specific objective.",
    },

    "explore": {
        "kind": "pi.dev",
        "label": "/explore <instruction>",
        "description": "Spawn a locked read-only Explore sub-agent for discovery.",
    },
    "coder": {
        "kind": "pi.dev",
        "label": "/coder <instruction>",
        "description": "Spawn a locked Coder sub-agent for scoped implementation.",
    },
    "verify": {
        "kind": "pi.dev",
        "label": "/verify <instruction>",
        "description": "Spawn a locked Verify sub-agent for adversarial testing and checks.",
    },
    "general": {
        "kind": "pi.dev",
        "label": "/general <instruction>",
        "description": "Spawn a locked General-purpose sub-agent.",
    },
    "chain": {
        "kind": "pi.dev",
        "label": "/chain <instruction>",
        "description": "Run the default Explore → Plan → Coder → Verify specialist chain.",
    },
    "help": {
        "kind": "help",
        "label": "/help",
        "description": "Show available slash commands.",
    },
}


def list_session_slash_commands() -> list[dict[str, str]]:
    return [
        {
            "verb": verb,
            "kind": spec["kind"],
            "label": spec["label"],
            "description": spec["description"],
            "tool": spec.get("tool", ""),
        }
        for verb, spec in SESSION_SLASH_COMMANDS.items()
    ]


def parse_session_slash_command(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text.startswith("/"):
        return None
    try:
        parts = shlex_split(text[1:])
    except ValueError:
        parts = text[1:].split()
    verb = (parts.pop(0) if parts else "").lower()
    spec = SESSION_SLASH_COMMANDS.get(verb)
    if not spec:
        return {"kind": "unknown", "verb": verb, "error": f"Unknown slash command: /{verb}. Use /help."}
    if spec["kind"] == "help":
        return {"kind": "help", "verb": verb}
    if spec["kind"] == "session" and verb == "compact":
        return {
            "kind": "compact",
            "verb": verb,
            "prompt": "Compact session context",
            "metadata": {"slash_command": "compact", "context_action": "compact"},
        }
    if spec["kind"] == "session" and verb == "model":
        fallback: list[str] = []
        role = "session"
        remaining: list[str] = []
        for part in parts:
            if part.startswith("--fallback="):
                fallback.extend([item.strip() for item in part.split("=", 1)[1].split(",") if item.strip()])
            elif part == "--fallback":
                continue
            elif part.startswith("--role="):
                role = part.split("=", 1)[1].strip() or "session"
            else:
                remaining.append(part)
        selector = " ".join(remaining).strip()
        return {
            "kind": "model",
            "verb": verb,
            "prompt": f"Switch session model to {selector}" if selector else "Show available session models",
            "selector": selector,
            "fallback": fallback,
            "role": role,
            "metadata": {"slash_command": "model", "model_selector": selector, "model_fallback_selectors": fallback, "model_role": role},
        }
    if spec["kind"] == "session" and verb == "plan":
        instruction = " ".join(parts).strip()
        return {
            "kind": "plan",
            "verb": verb,
            "prompt": instruction or "Plan the current request",
            "metadata": {"slash_command": "plan", "always_plan": True, "plan_only": True},
        }
    if spec["kind"] == "pi.dev" and verb == "chain":
        instruction = " ".join(parts).strip()
        return {
            "kind": "subagent_chain",
            "verb": verb,
            "prompt": instruction or "Run specialist chain",
            "instruction": instruction,
            "chain": "code_change",
            "profiles": ["explore", "plan", "coder", "verify"],
            "metadata": {
                "slash_command": verb,
                "subagent_chain": "code_change",
                "subagent_chain_profiles": ["explore", "plan", "coder", "verify"],
                "subagent_instruction": instruction,
            },
        }
    if spec["kind"] == "pi.dev":
        profile_key = None
        if verb == "subagent" and parts:
            maybe_profile = parts[0].lower().strip()
            if maybe_profile in {"explore", "plan", "coder", "verify", "general", "default", "inspect", "review", "test", "code"}:
                profile_key = parts.pop(0)
        elif verb in {"explore", "coder", "verify", "general"}:
            profile_key = verb
        instruction = " ".join(parts).strip()
        return {
            "kind": "subagent",
            "verb": verb,
            "prompt": instruction or "Subagent task",
            "instruction": instruction,
            "profile": profile_key,
            "metadata": {
                "slash_command": verb,
                "subagent": True,
                "subagent_instruction": instruction,
                "subagent_profile": profile_key,
            },
        }
    if verb == "command":
        tool = (parts.pop(0) if parts else "").strip()
        if not tool:
            return {"kind": "unknown", "verb": verb, "error": "Usage: /command <tool> [args]"}
        prompt = f"Run endpoint tool: {tool} {' '.join(parts)}".strip()
        return {
            "kind": "tool",
            "verb": verb,
            "tool": tool,
            "args": parts,
            "prompt": prompt,
            "command": f"tool:{tool}",
            "metadata": {"slash_command": "command", "tool_name": tool, "args": parts, "tool_invocation": True},
        }
    prompt = f"Run endpoint tool: {spec.get('tool') or verb} {' '.join(parts)}".strip()
    return {
        "kind": "tool",
        "verb": verb,
        "tool": spec.get("tool") or verb,
        "args": parts,
        "prompt": prompt,
        "command": f"tool:{spec.get('tool') or verb}",
        "metadata": {"slash_command": verb, "tool_name": spec.get("tool") or verb, "args": parts, "tool_invocation": True},
    }


def slash_help_text() -> str:
    return "\n".join(f"{spec['label']} - {spec['description']}" for spec in SESSION_SLASH_COMMANDS.values())
