#!/usr/bin/env python3
from __future__ import annotations
import re, sys
from pathlib import Path

APPDIR = Path(__file__).resolve().parents[1]
TEMP = APPDIR / ".changelog_temp.md"

def main():
    version = sys.argv[1].strip() if len(sys.argv) > 1 else input("Version: ").strip()
    if not version: raise SystemExit("usage: generate-changelog.py <version>")
    if not TEMP.exists(): print(f"{TEMP} not found"); return 1
    raw = TEMP.read_text(encoding="utf-8")
    in_section = False
    entries = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_section = s in ("## " + version, "## v" + version)
            continue
        if in_section and s.startswith("["):
            idx = s.index("]")
            text = s[idx+1:].strip()
            if text: entries.append(text.capitalize())
    if not entries: print(f"No entries for {version}"); return 1
    out = APPDIR / f"changed_{version}.txt"
    out.write_text("\n".join(f"- {e}" for e in entries) + "\n", encoding="utf-8")
    print(f"Written: {out} ({len(entries)} entries)")

if __name__ == "__main__": raise SystemExit(main())
