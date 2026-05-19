"""Let's Encrypt certificate management for PAC public HTTPS."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from .platform_home import pacp_path

LE_API_V2 = "https://acme-v02.api.letsencrypt.org/directory"

LE_DIR = pacp_path("letsencrypt")
LE_DIR.mkdir(parents=True, exist_ok=True)


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _check_domain_resolution(domain: str) -> bool:
    """Check if the domain resolves to this machine's public IP."""
    try:
        addrs = socket.getaddrinfo(domain, 80, type=socket.SOCK_STREAM)
        if not addrs:
            return False
        resolved_ip = addrs[0][4][0]
        # Check against our public IP
        try:
            req = urllib.request.Request('https://api.ipify.org?format=json')
            with urllib.request.urlopen(req, timeout=5) as r:
                public_ip = json.loads(r.read())['ip']
            return resolved_ip == public_ip
        except Exception:
            # Can't determine public IP — assume resolution works if we got an address
            return True
    except Exception:
        return False


def certbot_flow(domain: str, email: str, cert_dir: Path, challenge_port: int = 80) -> dict[str, Any]:
    """
    Use the certbot binary (if available) to get a Let's Encrypt certificate.
    This is the preferred path when certbot is installed.
    """
    certbot = shutil.which('certbot')
    if not certbot:
        return {"ok": False, "error": "certbot not found — install certbot with: apt install certbot"}

    cmd = [
        certbot, 'certonly',
        '--standalone',
        '--http-01-port', str(challenge_port),
        '-d', domain,
        '--email', email,
        '--agree-tos',
        '--noninteractive',
        '--keep',
        '--cert-name', f'pac-{domain}',
        '--config-dir', str(cert_dir / 'config'),
        '--work-dir', str(cert_dir / 'work'),
        '--logs-dir', str(cert_dir / 'logs'),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode == 0:
        # Find the cert
        conf_dir = cert_dir / 'config' / 'live' / f'pac-{domain}'
        cert_file = conf_dir / 'fullchain.pem'
        key_file = conf_dir / 'privkey.pem'
        if cert_file.exists() and key_file.exists():
            return {"ok": True, "cert_file": str(cert_file), "key_file": str(key_file)}
        return {"ok": True, "message": result.stdout}
    return {"ok": False, "error": result.stderr or 'certbot failed'}


def install_letsencrypt_cert(domain: str, config_obj: Any) -> dict[str, Any]:
    """Check domain, run certbot, copy cert to configured paths."""
    le_conf = config_obj.letsencrypt
    cert_dir = Path(le_conf.cert_file).expanduser().parent
    challenge_port = le_conf.challenge_port or 80

    # Check domain resolution
    resolved = _check_domain_resolution(domain)
    if not resolved:
        return {
            "ok": False,
            "error": (
                f"Domain {domain} does not resolve to this machine's public IP. "
                "Ensure A/AAAA record points here before enabling."
            ),
        }

    # Run certbot
    result = certbot_flow(domain, le_conf.email, cert_dir, challenge_port)
    if not result.get("ok"):
        return result

    # Copy cert to configured paths
    dest_cert = Path(le_conf.cert_file).expanduser()
    dest_key = Path(le_conf.key_file).expanduser()
    dest_cert.parent.mkdir(parents=True, exist_ok=True)

    src_cert = Path(result["cert_file"])
    src_key = Path(result["key_file"])
    shutil.copy2(src_cert, dest_cert)
    shutil.copy2(src_key, dest_key)

    return {
        "ok": True,
        "cert_file": str(dest_cert),
        "key_file": str(dest_key),
        "domain": domain,
    }