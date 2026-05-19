"""ACME DNS-01 client using Python stdlib only. No pip dependencies."""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

LE_DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"
LE_STAGING_DIRECTORY = "https://acme-staging-v02.api.letsencrypt.org/directory"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _generate_ec_key() -> str:
    """Generate a P-256 EC private key. Returns PEM."""
    result = subprocess.run(
        ['openssl', 'ecparam', '-genkey', '-name', 'prime256v1', '-out', '/dev/stdout'],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"openssl ecparam failed: {result.stderr}")
    return result.stdout


def _jwk_from_pem(pem: str) -> dict[str, str]:
    """Extract the JWK (x, y, crv) from an EC P-256 PEM key."""
    result = subprocess.run(
        ['openssl', 'ec', '-in', '/dev/stdin', '-pubout', '-text', '-noout'],
        input=pem.encode(), capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"openssl ec pubout failed: {result.stderr}")

    lines = result.stdout.strip().split('\n')
    hex_line = None
    for line in lines:
        line = line.strip()
        if line.startswith('04'):
            hex_line = line
            break

    if not hex_line:
        raise RuntimeError(f"Could not parse EC pubkey from openssl output: {result.stdout}")

    hex_bytes = bytes.fromhex(hex_line[2:])
    if len(hex_bytes) != 64:
        raise RuntimeError(f"Expected 64-byte pubkey, got {len(hex_bytes)}")

    x = _b64url(hex_bytes[:32])
    y = _b64url(hex_bytes[32:])

    return {"kty": "EC", "crv": "P-256", "x": x, "y": y}


def _sign_jws(payload_bytes: bytes, pem: str, kid: str | None, url: str) -> dict[str, str]:
    """Create a signed JWS. payload_bytes is already base64url-encoded raw content."""
    protected = {"alg": "ES256", "url": url}
    if kid:
        protected["kid"] = kid
    else:
        jwk = _jwk_from_pem(pem)
        protected["jwk"] = jwk

    protected_b64 = _b64url(json.dumps(protected, separators=(',', ':')).encode())

    signing_input = f"{protected_b64}.{payload_bytes.decode() if isinstance(payload_bytes, bytes) else payload_bytes}".encode()

    with tempfile.NamedTemporaryFile(suffix='.pem', mode='w', delete=False) as f:
        f.write(pem)
        key_file = f.name

    try:
        result = subprocess.run(
            ['openssl', 'dgst', '-sha256', '-sign', key_file],
            input=signing_input, capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"openssl sign failed: {result.stderr}")
        sig_b64 = _b64url(result.stdout)
    finally:
        os.unlink(key_file)

    return {
        "protected": protected_b64,
        "payload": payload_bytes.decode() if isinstance(payload_bytes, bytes) else payload_bytes,
        "signature": sig_b64,
    }


def _acme_request(url: str, payload: dict | None, pem: str, kid: str | None, method: str = 'POST') -> dict[str, Any]:
    """Make an ACME POST request."""
    payload_b64 = _b64url(json.dumps(payload or {}).encode()) if payload else ""

    jws = _sign_jws(payload_b64.encode(), pem, kid, url)

    headers = {"Content-Type": "application/jose+json"}
    data = json.dumps(jws).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_headers = dict(resp.headers)
            location = resp_headers.get('Location', '')
            retry_after = resp_headers.get('Retry-After')
            body = json.loads(resp.read())
            return {"body": body, "location": location, "retry_after": retry_after, "status_code": resp.status}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return {"body": body, "location": e.headers.get('Location', ''), "status_code": e.code, "error": body}


class ACMEClient:
    """Minimal ACME DNS-01 client. No external dependencies."""

    def __init__(self, account_key_pem: str, email: str, staging: bool = False):
        self.account_key_pem = account_key_pem
        self.email = email
        self.directory_url = LE_STAGING_DIRECTORY if staging else LE_DIRECTORY
        self.kid: str | None = None
        self._directory: dict[str, Any] | None = None

    def _get_directory(self) -> dict[str, Any]:
        if self._directory is None:
            req = urllib.request.Request(self.directory_url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                self._directory = json.loads(resp.read())
        return self._directory

    def register(self) -> dict[str, Any]:
        """Register a new ACME account."""
        dir_data = self._get_directory()
        new_account_url = dir_data.get('newAccount', dir_data.get('url', self.directory_url))

        payload = {"termsOfServiceAgreed": True, "email": self.email}
        result = _acme_request(new_account_url, payload, self.account_key_pem, kid=None)

        if result.get('status_code') in (200, 201):
            self.kid = result.get('location', '')
            return {"ok": True, "kid": self.kid}

        if result.get('status_code') == 409:
            self.kid = result.get('location', '')
            return {"ok": True, "kid": self.kid, "reused": True}

        errors = result.get('body', {}).get('error', {})
        return {"ok": False, "error": f"ACME registration failed: {errors}"}

    def authorize_domain(self, domain: str) -> dict[str, Any]:
        """Create a DNS-01 authorization for a domain. Returns challenge info."""
        dir_data = self._get_directory()
        new_authz_url = dir_data.get('newAuthz', dir_data.get('newAuthorization', dir_data.get('url')))

        if not new_authz_url:
            return {"ok": False, "error": "No newAuthz URL in directory"}

        payload = {"identifier": {"type": "dns", "value": domain}}
        result = _acme_request(new_authz_url, payload, self.account_key_pem, self.kid, url=new_authz_url)

        if result.get('status_code') not in (200, 201):
            errors = result.get('body', {}).get('error', {})
            return {"ok": False, "error": f"Authorization failed: {errors}"}

        authz = result.get('body', {})

        dns_challenge = None
        for challenge in authz.get('challenges', []):
            if challenge.get('type') == 'dns-01':
                dns_challenge = challenge
                break

        if not dns_challenge:
            return {"ok": False, "error": f"No DNS-01 challenge offered for {domain}"}

        token = dns_challenge.get('token', '')

        jwk = _jwk_from_pem(self.account_key_pem)
        jwk_json = json.dumps(jwk, separators=(',', ':')).encode()
        jwk_hash = hashlib.sha256(jwk_json).digest()
        jwk_thumbprint = _b64url(jwk_hash)

        key_auth = f"{token}.{jwk_thumbprint}"

        ka_bytes = key_auth.encode()
        ka_hash = hashlib.sha256(ka_bytes).digest()
        dns_content = _b64url(ka_hash)

        return {
            "ok": True,
            "domain": domain,
            "authorization_url": authz.get('url', ''),
            "challenge_url": dns_challenge.get('url', ''),
            "token": token,
            "key_authorization": key_auth,
            "dns_content": dns_content,
            "challenge": dns_challenge,
        }

    def trigger_challenge(self, challenge_url: str, key_auth: str) -> dict[str, Any]:
        """Notify ACME that DNS challenge is ready (POST to challenge URL)."""
        payload = {"keyAuthorization": key_auth}
        result = _acme_request(challenge_url, payload, self.account_key_pem, self.kid, url=challenge_url)

        if result.get('status_code') in (200, 201):
            return {"ok": True, "body": result.get('body', {})}

        errors = result.get('body', {}).get('error', {})
        return {"ok": False, "error": f"Challenge trigger failed: {errors}"}

    def poll_authorization(self, authz_url: str, max_wait: int = 60) -> dict[str, Any]:
        """Poll until the DNS-01 challenge is verified."""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            result = _acme_request(authz_url, None, self.account_key_pem, self.kid, url=authz_url)

            if result.get('status_code') not in (200, 201):
                errors = result.get('body', {}).get('error', {})
                return {"ok": False, "error": f"Authorization poll failed: {errors}"}

            authz = result.get('body', {})
            for challenge in authz.get('challenges', []):
                if challenge.get('type') == 'dns-01':
                    status = challenge.get('status', 'pending')
                    if status == 'valid':
                        return {"ok": True, "authorized": True, "authz": authz}
                    elif status == 'pending':
                        pass
                    elif status == 'invalid':
                        error = challenge.get('error', {})
                        return {"ok": False, "error": f"DNS-01 invalid: {error}"}

            time.sleep(2)

        return {"ok": False, "error": "Authorization timed out"}

    def finalize(self, domains: list[str], cert_key_pem: str) -> dict[str, Any]:
        """Create CSR and finalize. Returns certificate."""
        dir_data = self._get_directory()
        new_cert_url = dir_data.get('newCertificate') or dir_data.get('newCert')

        if not new_cert_url:
            return {"ok": False, "error": "No newCertificate URL in directory"}

        csr_result = subprocess.run(
            ['openssl', 'req', '-new', '-key', '/dev/stdin', '-sha256', '-subj', f'/CN={domains[0]}'],
            input=cert_key_pem.encode(), capture_output=True, text=True, timeout=10,
        )
        if csr_result.returncode != 0:
            return {"ok": False, "error": f"CSR generation failed: {csr_result.stderr}"}

        csr_pem = csr_result.stdout
        csr_der_b64 = _b64url(subprocess.run(
            ['openssl', 'req', '-in', '/dev/stdin', '-outform', 'DER'],
            input=csr_pem.encode(), capture_output=True, text=True, timeout=10,
        ).stdout.encode())

        payload = {"csr": csr_der_b64}
        result = _acme_request(new_cert_url, payload, self.account_key_pem, self.kid, url=new_cert_url)

        if result.get('status_code') in (200, 201):
            body = result.get('body', {})
            cert_pem = body.get('certificate', '')
            return {"ok": True, "certificate": cert_pem, "issuance": body}

        errors = result.get('body', {}).get('error', {})
        return {"ok": False, "error": f"Certificate issuance failed: {errors}"}