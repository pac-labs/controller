"""DNS provider integration for ACME DNS-01 challenges. Cloudflare only for now."""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from typing import Any

CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"


def _cloudflare_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }


def _cf_get(path: str, api_token: str) -> dict[str, Any]:
    url = f"{CLOUDFLARE_API}{path}"
    req = urllib.request.Request(url, headers=_cloudflare_headers(api_token))
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _cf_post(path: str, api_token: str, data: dict | None = None) -> dict[str, Any]:
    url = f"{CLOUDFLARE_API}{path}"
    body = json.dumps(data or {}).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=_cloudflare_headers(api_token))
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _cf_delete(path: str, api_token: str) -> dict[str, Any]:
    url = f"{CLOUDFLARE_API}{path}"
    req = urllib.request.Request(url, headers=_cloudflare_headers(api_token), method='DELETE')
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def cloudflare_create_txt_record(zone_id: str, api_token: str, name: str, content: str, proxied: bool = False) -> dict[str, Any]:
    """Create a TXT DNS record. Returns the record result."""
    payload = {
        "type": "TXT",
        "name": name,
        "content": content,
        "proxiied": proxied,
        "ttl": 120,
    }
    result = _cf_post(f"/zones/{zone_id}/dns_records", api_token, payload)
    return result


def cloudflare_delete_txt_record(zone_id: str, api_token: str, record_id: str) -> dict[str, Any]:
    """Delete a DNS record by ID."""
    return _cf_delete(f"/zones/{zone_id}/dns_records/{record_id}", api_token)


def cloudflare_lookup_txt(zone_id: str, api_token: str, name: str) -> list[dict[str, Any]]:
    """List existing TXT records for a name."""
    encoded_name = name.replace('"', '%22')
    result = _cf_get(f"/zones/{zone_id}/dns_records?type=TXT&name={encoded_name}", api_token)
    records = result.get('result', [] if result.get('success') else [])
    return records


def test_cloudflare_credentials(api_token: str, zone_id: str) -> dict[str, Any]:
    """Test Cloudflare API token and zone ID. Returns {'ok': True} or {'ok': False, 'error': str}."""
    try:
        result = _cf_get(f"/zones/{zone_id}", api_token)
        if result.get('success') and result.get('result'):
            zone_name = result['result'].get('name', '')
            return {'ok': True, 'zone': zone_name, 'zone_id': zone_id}
        return {'ok': False, 'error': result.get('errors', [{}])[0].get('message', 'Invalid response')}
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read())
            msg = err_body.get('errors', [{}])[0].get('message', str(e))
        except Exception:
            msg = str(e)
        return {'ok': False, 'error': f"Cloudflare API error: {msg}"}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}