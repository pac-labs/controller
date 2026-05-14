"""PAC TLS certificate management — CA, agent certs, user certs."""
from pathlib import Path
import subprocess, datetime, uuid, hashlib

# ── Paths ───────────────────────────────────────────────────────────
BASE = Path("/home/dorbian/.pacp/config/tls")
CA_DIR = str(BASE)
CA_CERT_PATH = str(BASE / "pac-root-ca.crt")
CA_KEY_PATH = str(BASE / "private" / "pac-root-ca.key")
CA_EXT_PATH = str(BASE / "ca.ext")

def run(cmd, cwd=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {r.stderr}")
    return r.stdout

def ensure_ca_ext():
    """Create openssl ext file for CA cert signing."""
    ext = """authorityKeyIdentifier=keyid:always
basicConstraints=CA:TRUE,pathlen:0
keyUsage=keyCertSign,crlSign,digitalSignature
"""
    Path(CA_EXT_PATH).write_text(ext)

def sign_agent_cert(workspace: str, cn: str) -> tuple[str, str, str]:
    """Generate and sign an agent certificate for a workspace."""
    import tempfile, os
    tmp = tempfile.mkdtemp()
    key_path = os.path.join(tmp, f"{cn}.key")
    csr_path = os.path.join(tmp, f"{cn}.csr")
    cert_path = os.path.join(tmp, f"{cn}.crt")

    # Generate key
    run(f"openssl genrsa -out {key_path} 2048")
    # Generate CSR
    run(f'openssl req -new -key {key_path} -out {csr_path} -subj "/CN={cn}/O=PAC/L=Local"')
    # Sign with CA
    run(f'openssl x509 -req -in {csr_path} -CA {CA_CERT_PATH} -CAkey {CA_KEY_PATH} '
        f'-CAcreateserial -out {cert_path} -days 365 -sha256 '
        f'-extfile {CA_EXT_PATH}' if Path(CA_EXT_PATH).exists()
        else f'openssl x509 -req -in {csr_path} -CA {CA_CERT_PATH} -CAkey {CA_KEY_PATH} '
        f'-CAcreateserial -out {cert_path} -days 365 -sha256')

    # Copy to persistent location
    dest_dir = Path(BASE) / "certs" / "agents"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_cert = dest_dir / f"{workspace}.crt"
    dest_key = dest_dir / f"{workspace}.key"
    Path(cert_path).copyfile(dest_cert)
    Path(key_path).copyfile(dest_key)

    return str(dest_cert), str(dest_key), csr_path

def sign_user_cert(user_id: str) -> tuple[str, str]:
    """Generate and sign a user certificate."""
    import tempfile, os
    tmp = tempfile.mkdtemp()
    cn = f"human-{user_id}"
    key_path = os.path.join(tmp, f"{cn}.key")
    csr_path = os.path.join(tmp, f"{cn}.csr")
    cert_path = os.path.join(tmp, f"{cn}.crt")

    run(f"openssl genrsa -out {key_path} 2048")
    run(f'openssl req -new -key {key_path} -out {csr_path} -subj "/CN={cn}/O=PAC-Users/L=Local"')
    run(f'openssl x509 -req -in {csr_path} -CA {CA_CERT_PATH} -CAkey {CA_KEY_PATH} '
        f'-CAcreateserial -out {cert_path} -days 365 -sha256')

    dest_dir = Path(BASE) / "certs" / "users"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_cert = dest_dir / f"{user_id}.crt"
    dest_key = dest_dir / f"{user_id}.key"
    Path(cert_path).copyfile(dest_cert)
    Path(key_path).copyfile(dest_key)

    return str(dest_cert), str(dest_key)

def verify_peer_cert(cert_pem: str, ca_cert_pem: str) -> dict:
    """Verify a peer certificate against the CA. Returns cert info or raises."""
    import tempfile, ssl, cryptography
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes

    # Load cert
    cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
    # Load CA
    ca = x509.load_pem_x509_certificate(ca_cert_pem.encode(), default_backend())
    # Verify signature
    ca.public_key().verify(cert.signature, cert.tbs_certificate_bytes, ca.public_key().algorithm)
    # Return subject
    cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
    return {"cn": cn, "valid": True}

def get_cert_cn(cert_pem: str) -> str:
    """Extract CN from a PEM certificate."""
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
    return cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
