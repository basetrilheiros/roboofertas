"""Versioned Fernet encryption; authenticated legacy decoding only for migration."""
import base64
import hashlib
import hmac
import os
from pathlib import Path
from cryptography.fernet import Fernet
from config import DATA_DIR
DEFAULT_KEY_FILE = DATA_DIR / ".app_secret_key"

def get_or_create_master_key(key_file=DEFAULT_KEY_FILE):
    key_file = Path(key_file)
    secret = os.environ.get("BASETRILHEIROS_MASTER_SECRET")
    if secret and key_file == DEFAULT_KEY_FILE:
        if len(secret) < 32:
            raise ValueError("A chave mestre do servidor é inválida.")
        return base64.urlsafe_b64encode(hashlib.sha256(("fernet-online:"+secret).encode()).digest())
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        try:
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key()); f.flush(); os.fsync(f.fileno())
    key = key_file.read_bytes()
    if len(key) != 32:
        Fernet(key)  # Validate without replacing an invalid key.
    os.chmod(key_file, 0o600)
    return key

def get_fernet(key_file=DEFAULT_KEY_FILE):
    key = get_or_create_master_key(key_file)
    # Legacy binary keys remain byte-for-byte unchanged.
    return Fernet(base64.urlsafe_b64encode(key) if len(key) == 32 else key)

def encrypt_secret(plaintext, key_file=DEFAULT_KEY_FILE):
    return "fernet:v1:" + get_fernet(key_file).encrypt(plaintext.encode()).decode() if plaintext else None

def decrypt_secret(token_str, key_file=DEFAULT_KEY_FILE):
    if not token_str: return None
    try:
        # Never silently create a replacement key when decrypting existing data.
        if not Path(key_file).is_file() and not (Path(key_file)==DEFAULT_KEY_FILE and os.environ.get("BASETRILHEIROS_MASTER_SECRET")): raise ValueError("Chave ausente")
        if token_str.startswith("fernet:v1:"):
            return get_fernet(key_file).decrypt(token_str[10:].encode()).decode()
        if token_str.startswith("gAAAA"):
            return get_fernet(key_file).decrypt(token_str.encode()).decode()
        raw = bytes.fromhex(token_str)
        if len(raw) < 48: raise ValueError("Formato legado inválido")
        nonce, tag, cipher = raw[:16], raw[16:48], raw[48:]
        key = get_or_create_master_key(key_file)
        if not hmac.compare_digest(tag, hmac.new(key, nonce+cipher, hashlib.sha256).digest()):
            raise ValueError("Integridade inválida")
        stream = b"".join(hmac.new(key, nonce+i.to_bytes(4,"big"), hashlib.sha256).digest()
                          for i in range((len(cipher)+31)//32))
        return bytes(a^b for a,b in zip(cipher,stream)).decode()
    except Exception:
        raise ValueError("Falha na autenticação do segredo: dados ou chave inválidos.") from None
