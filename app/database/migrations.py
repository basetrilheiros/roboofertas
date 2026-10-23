"""
Sistema simples de migrações locais e sequenciais para o SQLite.
Preserva integralmente dados existentes a cada etapa.
"""
from pathlib import Path
from typing import Optional

from database.connection import get_db, init_db

PHASE2_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_phase2.sql"


def ensure_database(db_path: Optional[Path] = None) -> None:
    """Garante a aplicação sequencial e idempotente de todas as migrações."""
    with get_db(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 1. Esquema da Fase 1 (Fundação, Vendas e Parâmetros)
        row1 = conn.execute("SELECT 1 FROM _migrations WHERE name = '0001_initial_schema'").fetchone()
        if not row1:
            init_db(db_path)
            conn.execute("INSERT INTO _migrations (name) VALUES ('0001_initial_schema');")

        # 2. Esquema da Fase 2 (Descoberta, Histórico de Preços e Credenciais)
        row2 = conn.execute("SELECT 1 FROM _migrations WHERE name = '0002_phase2_discovery_and_prices'").fetchone()
        if not row2:
            if PHASE2_SCHEMA_PATH.exists():
                with open(PHASE2_SCHEMA_PATH, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
            conn.execute("INSERT INTO _migrations (name) VALUES ('0002_phase2_discovery_and_prices');")
