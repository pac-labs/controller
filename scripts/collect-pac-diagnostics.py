#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Download a sanitized PAC session diagnostics zip.')
    parser.add_argument('session_id', help='PAC session id, for example sess_abcd1234')
    parser.add_argument('--url', default=os.environ.get('PAC_URL', 'http://127.0.0.1:8000'), help='PAC controller base URL; defaults to PAC_URL or localhost:8000')
    parser.add_argument('--token', default=os.environ.get('PAC_TOKEN', ''), help='Optional PAC API token; defaults to PAC_TOKEN')
    parser.add_argument('--events', type=int, default=1000, help='Number of session events to include, 1-10000')
    parser.add_argument('--full', action='store_true', help='Include full model/event text instead of conservative truncation')
    parser.add_argument('--no-workspace-state', action='store_true', help='Skip workspace git status/diff/file sample')
    parser.add_argument('-o', '--output', default='', help='Output zip path')
    args = parser.parse_args()

    base = args.url.rstrip('/')
    query = urllib.parse.urlencode({
        'include_events': max(1, min(args.events, 10000)),
        'full': 'true' if args.full else 'false',
        'include_workspace_state': 'false' if args.no_workspace_state else 'true',
    })
    endpoint = f'{base}/v1/sessions/{urllib.parse.quote(args.session_id)}/diagnostics.zip?{query}'
    out_path = Path(args.output or f'pac-diagnostics-{args.session_id}.zip')
    headers = {}
    if args.token:
        headers['Authorization'] = f'Bearer {args.token}'
    req = urllib.request.Request(endpoint, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:1000]
        print(f'PAC diagnostics download failed: HTTP {exc.code}: {detail}', file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'PAC diagnostics download failed: {exc}', file=sys.stderr)
        return 1
    out_path.write_bytes(data)
    print(out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
