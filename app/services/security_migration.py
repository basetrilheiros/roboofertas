from contextlib import closing
"""All-or-nothing encryption upgrade with SQLite backup and matching key."""
import os
import shutil
import sqlite3
import uuid
from pathlib import Path
from services.crypto import DEFAULT_KEY_FILE, decrypt_secret, encrypt_secret
FIELDS = ("client_secret_encrypted", "access_token_encrypted", "refresh_token_encrypted")

def migrate_security(db_path, key_file=DEFAULT_KEY_FILE):
    db_path, key_file = Path(db_path), Path(key_file)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS security_versions (version TEXT PRIMARY KEY)")
        if conn.execute("SELECT 1 FROM security_versions WHERE version='2.1-A'").fetchone():
            conn.rollback(); return
        row = conn.execute("SELECT client_secret_encrypted,access_token_encrypted,refresh_token_encrypted FROM ml_credentials WHERE id=1").fetchone()
        # Authenticate ALL values before changing any of them.
        values = [encrypt_secret(decrypt_secret(v,key_file),key_file) if v else None for v in row]
        backup = db_path.parent / "backups" / ("pre_2_1_A_"+uuid.uuid4().hex)
        backup.mkdir(parents=True, mode=0o700)
        # Independent read connection includes committed WAL content while writer lock is held.
        with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(backup/"database.db")) as dest:
            source.backup(dest)
        os.chmod(backup/"database.db",0o600)
        if key_file.exists():
            shutil.copy2(key_file,backup/"master.key"); os.chmod(backup/"master.key",0o600)
        conn.execute("UPDATE ml_credentials SET client_secret_encrypted=?,access_token_encrypted=?,refresh_token_encrypted=? WHERE id=1",values)
        conn.execute("CREATE TABLE IF NOT EXISTS oauth_pending (state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, verifier_encrypted TEXT NOT NULL, redirect_uri TEXT NOT NULL, expires_at INTEGER NOT NULL)")
        conn.execute("INSERT INTO security_versions VALUES ('2.1-A')")
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()
