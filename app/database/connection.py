"""
Gerenciamento de conexões com o banco SQLite.
Garante foreign_keys ativas, WAL mode e row_factory padronizada.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from config import DB_PATH

def is_postgres(target):
    return isinstance(target, str) and target.startswith(("postgres://", "postgresql://"))


SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Cria e configura uma conexão com SQLite."""
    target_path = db_path or DB_PATH
    if is_postgres(target_path):
        from database.postgres import Connection
        return Connection(str(target_path))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(
        str(target_path),
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        timeout=10.0,
    )
    conn.row_factory = sqlite3.Row
    
    # Pragmas de performance, integridade e concorrência local
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


@contextmanager
def get_db(db_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager para gerenciar transações no banco de dados."""
    conn = connect_db(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """Executa o script de inicialização do esquema."""
    with get_db(db_path) as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
