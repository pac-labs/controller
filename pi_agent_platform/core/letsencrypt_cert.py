"""Let's Encrypt certificate issuance via DNS-01 (Cloudflare)."""
from __future__ import annotations
import json
import os
import re
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from .dns_providers import cloudflare_create_txt_record, cloudflare_delete_txt_record, test_cloudflare_credentials
from .acme_dns01 import ACMEClient, _b64url, _generate_ec_key, _jwk_from_pem
from .platform_home import pacp_path

LE_API = "https://acme-v02.api.letsencrypt.org/directory"
LE_STAGING_API = "https://acme-staging-v02.api.letsencrypt.org/directory"


def _get_account_key_path() -> Path:
    return pacp_path("letsencrypt", "account_key.pem")


def _load_or_create_account_key() -> str:
    """Load existing account key or create a new one."""
    key_path = _get_account_key_path()
    if key_path.exists():
        return key_path.read_text()

    pem = _generate_ec_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(pem)
    os.chmod(key_path, 0o600)
    return pem


def _get_cloudflare_config() -> tuple[str, str]:
    """Load Cloudflare zone_id and api_token from config."""
    try:
        from .config import config as global_config
        le = getattr(global_config, 'letsencrypt', None) or {}
        if hasattr(le, 'cloudflare_zone_id'):
            return str(le.cloudflare_zone_id or ''), str(le.cloudflare_api_token or '')
    except Exception:
        pass
    return "", ""


def _get_letsencrypt_config() -> dict[str, Any]:
    """Get current letsencrypt config."""
    try:
        from .config import config as global_config
        le = getattr(global_config, 'letsencrypt', None) or {}
        if hasattr(le, 'model_dump'):
            return le.model_dump()
        return {
            "cert_file": getattr(le, 'cert_file', '~/.pacp/config/letsencrypt/cert.pem'),
            "key_file": getattr(le, 'key_file', '~/.pacp/config/letsencrypt/key.pem'),
            "email": getattr(le, 'email', ''),
            "domain": getattr(le, 'domain', ''),
        }
    except Exception:
        return {}


def issue_letsencrypt_certificate(domain: str, email: str, staging: bool = False) -> dict[str, Any]:
    """
    Full DNS-01 certificate issuance for domain using Cloudflare.
    Returns {"ok": True, "cert_file": ..., "key_file": ...} or {"ok": False, "error": ...}
    """
    zone_id, api_token = _get_cloudflare_config()
    if not zone_id or not api_token:
        return {"ok": False, "error": "Cloudflare credentials not configured in PAC settings"}

    cred_test = test_cloudflare_credentials(api_token, zone_id)
    if not cred_test.get('ok'):
        return {"ok": False, "error": f"Cloudflare credentials invalid: {cred_test.get('error')}"}

    le_dir = pacp_path("letsencrypt")
    le_dir.mkdir(parents=True, exist_ok=True)

    account_key = _load_or_create_account_key()

    client = ACMEClient(account_key, email, staging=staging)
    reg_result = client.register()
    if not reg_result.get('ok'):
        return {"ok": False, "error": reg_result.get('error', 'Registration failed')}

    auth_result = client.authorize_domain(domain)
    if not auth_result.get('ok'):
        return {"ok": False, "error": auth_result.get('error', 'Authorization failed')}

    dns_content = auth_result['dns_content']
    authz_url = auth_result['authorization_url']
    challenge_url = auth_result['challenge_url']
    key_auth = auth_result['key_authorization']

    record_name = f"_acme-challenge.{domain}"
    try:
        record_result = cloudflare_create_txt_record(zone_id, api_token, record_name, dns_content, proxied=False)
        if not record_result.get('success'):
            return {"ok": False, "error": f"Cloudflare TXT record creation failed: {record_result.get('errors', [{}])[0].get('message', record_result)}"}
        record_id = record_result.get('result', {}).get('id', '')
    except Exception as exc:
        return {"ok": False, "error": f"Cloudflare API error: {exc}"}

    print(f"Waiting for DNS propagation for {record_name}...")
    time.sleep(15)

    trigger_result = client.trigger_challenge(challenge_url, key_auth)
    if not trigger_result.get('ok'):
        try:
            cloudflare_delete_txt_record(zone_id, api_token, record_id)
        except Exception:
            pass
        return {"ok": False, "error": trigger_result.get('error', 'Challenge trigger failed')}

    print(f"Polling for DNS-01 validation...")
    poll_result = client.poll_authorization(authz_url, max_wait=90)
    if not poll_result.get('ok'):
        try:
            cloudflare_delete_txt_record(zone_id, api_token, record_id)
        except Exception:
            pass
        return {"ok": False, "error": poll_result.get('error', 'Authorization poll failed')}

    try:
        cloudflare_delete_txt_record(zone_id, api_token, record_id)
    except Exception:
        pass

    key_result = subprocess.run(
        ['openssl', 'genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve', 'prime256v1'],
        capture_output=True, text=True, timeout=10,
    )
    if key_result.returncode != 0:
        return {"ok": False, "error": f"Private key generation failed: {key_result.stderr}"}

    cert_key_pem = key_result.stdout

    finalize_result = client.finalize([domain], cert_key_pem)
    if not finalize_result.get('ok'):
        return {"ok": False, "error": finalize_result.get('error', 'Certificate issuance failed')}

    cert_pem = finalize_result.get('certificate', '')
    if not cert_pem:
        return {"ok": False, "error": "No certificate returned"}

    le_conf = _get_letsencrypt_config()
    cert_dest = Path(le_conf.get('cert_file', '~/.pacp/config/letsencrypt/cert.pem')).expanduser()
    key_dest = Path(le_conf.get('key_file', '~/.pacp/config/letsencrypt/key.pem')).expanduser()

    cert_dest.parent.mkdir(parents=True, exist_ok=True)
    cert_dest.write_text(cert_pem)
    key_dest.write_text(cert_key_pem)
    os.chmod(key_dest, 0o600)

    return {
        "ok": True,
        "cert_file": str(cert_dest),
        "key_file": str(key_dest),
        "domain": domain,
        "email": email,
    }


def check_domain_dns(domain: str) -> dict[str, Any]:
    """Check if domain resolves."""
    import socket
    try:
        addrs = socket.getaddrinfo(domain, 443)
        if addrs:
            return {"ok": True, "resolves": True, "ip": addrs[0][4][0]}
    except Exception:
        pass
    return {"ok": True, "resolves": False, "error": f"{domain} does not resolve"}


def get_letsencrypt_status() -> dict[str, Any]:
    """Return current LE configuration and cert info."""
    le_conf = _get_letsencrypt_config()
    cert_path = Path(le_conf.get('cert_file', '~/.pacp/config/letsencrypt/cert.pem')).expanduser()
    key_path = Path(le_conf.get('key_file', '~/.pacp/config/letsencrypt/key.pem')).expanduser()

    status = {
        "enabled": le_conf.get('enabled', False),
        "email": le_conf.get('email', ''),
        "domain": le_conf.get('domain', ''),
        "dns_provider": le_conf.get('dns_provider', 'cloudflare'),
        "cloudflare_configured": bool(le_conf.get('cloudflare_api_token') and le_conf.get('cloudflare_zone_id')),
        "cert_exists": cert_path.exists() and key_path.exists(),
        "cert_file": str(cert_path),
        "key_file": str(key_path),
    }

    if status["cert_exists"]:
        try:
            result = subprocess.run(
                ['openssl', 'x509', '-in', str(cert_path), '-noout', '-dates', '-subject'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                status["cert_info"] = {
                    "subject": lines[-1] if lines else '',
                    "not_before": lines[0].split('=', 1)[-1] if len(lines) > 0 else '',
                    "not_after": lines[1].split('=', 1)[-1] if len(lines) > 1 else '',
                }
        except Exception:
            pass

    return status