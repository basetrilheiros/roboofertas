"""Self-signed loopback certificate; never installs a trust anchor."""
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from config import DATA_DIR

def ensure_local_tls(directory=None):
    directory = directory or DATA_DIR / "tls"
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    cert, key = directory/"localhost.crt", directory/"localhost.key"
    if cert.exists() and key.exists(): return str(cert),str(key)
    private = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"localhost")])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
      .public_key(private.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=365))
      .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),critical=False)
      .sign(private,hashes.SHA256()))
    with os.fdopen(os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),"wb") as f:
        f.write(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return str(cert),str(key)
