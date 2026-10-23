"""Durable PKCE, browser binding, ten minute expiry, atomic single use."""
import hashlib
import time
from services.ml_auth import generate_pkce_pair, generate_state_token, build_authorization_url
from services.crypto import encrypt_secret, decrypt_secret, DEFAULT_KEY_FILE

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def begin(conn, client_id, redirect_uri, browser, key_file=DEFAULT_KEY_FILE, now=None):
    now = int(time.time()) if now is None else now
    state = generate_state_token()
    verifier, challenge = generate_pkce_pair()
    conn.execute("DELETE FROM oauth_pending WHERE expires_at<=? OR browser_hash=?",(now,digest(browser)))
    conn.execute("INSERT INTO oauth_pending VALUES (?,?,?,?,?)",(digest(state),digest(browser),encrypt_secret(verifier,key_file),redirect_uri,now+600))
    return build_authorization_url(client_id,redirect_uri,state,challenge)[0]

def consume(conn, state, browser, key_file=DEFAULT_KEY_FILE, now=None):
    now = int(time.time()) if now is None else now
    if not state or not browser: raise ValueError("Autorização inválida ou expirada")
    row = conn.execute("DELETE FROM oauth_pending WHERE state_hash=? AND browser_hash=? AND expires_at>? RETURNING verifier_encrypted,redirect_uri",(digest(state),digest(browser),now)).fetchone()
    if row is None: raise ValueError("Autorização inválida ou expirada")
    return decrypt_secret(row[0],key_file), row[1]
