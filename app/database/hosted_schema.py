"""Atomic, locked initialization of a new PostgreSQL database."""
from pathlib import Path
from database.connection import get_db

EXTRA = '''
CREATE TABLE IF NOT EXISTS security_versions (version TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS oauth_pending (
 state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, verifier_encrypted TEXT NOT NULL,
 redirect_uri TEXT NOT NULL, expires_at BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_throttle (
 bucket TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_start BIGINT NOT NULL);
INSERT INTO security_versions VALUES ('2.1-A') ON CONFLICT DO NOTHING;
'''

def ensure_hosted_schema(url):
    with get_db(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(71420902)')
        conn.execute('''CREATE TABLE IF NOT EXISTS _migrations (
          id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL,
          applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        for name, filename in [('0001_initial_schema','schema.sql'),('0002_phase2_discovery_and_prices','schema_phase2.sql')]:
            if not conn.execute('SELECT 1 FROM _migrations WHERE name=?',(name,)).fetchone():
                conn.executescript((Path(__file__).parent/filename).read_text(encoding='utf-8-sig'))
                conn.execute('INSERT INTO _migrations(name) VALUES (?)',(name,))
        conn.executescript(EXTRA)
        from services.affiliate_links import SCHEMA
        conn.execute(SCHEMA)
