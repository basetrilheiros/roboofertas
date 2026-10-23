"""PostgreSQL adapter for the application's small, explicit SQLite SQL subset."""
import re
import sqlite3
from psycopg import connect, IntegrityError
from psycopg.rows import dict_row

IDENTITY_TABLES = {'imports','sales','monitored_products','sale_status_history','audit_events',
 'scheduler_logs','discovery_runs','discovered_products','price_history','curated_offers','user_decisions_feedback','_migrations'}

class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)

class Cursor:
    def __init__(self, cursor, generated=False):
        self.cursor = cursor
        self.lastrowid = None
        if generated:
            row = cursor.fetchone()
            self.lastrowid = row['id'] if row else None
    def fetchone(self):
        row = self.cursor.fetchone()
        return Row(row) if row is not None else None
    def fetchall(self):
        return [Row(row) for row in self.cursor.fetchall()]
    @property
    def rowcount(self): return self.cursor.rowcount


def translate(sql):
    sql = re.sub(r'^\s*PRAGMA[^;]*;', '', sql, flags=re.M|re.I)
    sql = re.sub(r'INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY', sql, flags=re.I)
    ignored = bool(re.search(r'\bINSERT OR IGNORE INTO\b', sql, re.I))
    sql = re.sub(r'\bINSERT OR IGNORE INTO\b', 'INSERT INTO', sql, flags=re.I)
    if ignored:
        sql = sql.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
    # Parameter conversion outside SQL quoted strings; do not interpret user input as SQL.
    pieces = re.split(r"('(?:''|[^'])*')", sql)
    return ''.join(part if i%2 else part.replace('%', '%%').replace('?', '%s') for i,part in enumerate(pieces))

class Connection:
    dialect = 'postgresql'
    def __init__(self, url):
        self.raw = connect(url, row_factory=dict_row, connect_timeout=10, options='-c timezone=UTC -c statement_timeout=30000')
    def execute(self, sql, params=None):
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            # Serialize config/token rotation across workers, including existing transactions.
            sql = 'SELECT pg_advisory_xact_lock(71420901)'
        sql = translate(sql)
        match = re.match(r'\s*INSERT INTO\s+([a-z_]+)\b', sql, re.I)
        generated = bool(match and match.group(1) in IDENTITY_TABLES and not re.search(r'\bRETURNING\b',sql,re.I))
        if generated: sql = sql.rstrip().rstrip(';') + ' RETURNING id'
        try:
            cursor = self.raw.execute(sql, params if params is not None else None)
            return Cursor(cursor, generated)
        except IntegrityError:
            raise sqlite3.IntegrityError('Restrição de integridade do banco.') from None
    def executescript(self, sql):
        # Trusted schema files only. Split statements using psycopg's simple protocol.
        sql = re.sub(r'^\s*PRAGMA[^;]*;', '',sql,flags=re.M|re.I)
        sql = re.sub(r'INTEGER PRIMARY KEY AUTOINCREMENT','BIGSERIAL PRIMARY KEY',sql,flags=re.I)
        sql = re.sub(r'INSERT OR IGNORE INTO ([^;]+);',r'INSERT INTO \1 ON CONFLICT DO NOTHING;',sql,flags=re.I)
        self.raw.execute(sql, prepare=False)
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def close(self): self.raw.close()
