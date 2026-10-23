"""
Operações de auditoria, histórico de importações e logs do agendador.
"""
import json
import sqlite3
from typing import Any, Dict, List, Optional


def log_audit(
    conn: sqlite3.Connection,
    event_type: str,
    description: str,
    payload: Optional[Dict[str, Any]] = None,
) -> int:
    """Registra um evento no log de auditoria do sistema."""
    cursor = conn.execute(
        "INSERT INTO audit_events (event_type, description, payload_json) VALUES (?, ?, ?)",
        (event_type, description, json.dumps(payload, ensure_ascii=False) if payload else None),
    )
    return cursor.lastrowid


def list_audit_events(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    """Retorna os eventos mais recentes da auditoria."""
    cursor = conn.execute(
        "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def list_imports(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    """Retorna os registros de arquivos importados."""
    cursor = conn.execute(
        "SELECT * FROM imports ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_import(conn: sqlite3.Connection, import_id: int) -> Optional[Dict[str, Any]]:
    """Busca detalhes de uma importação por ID."""
    row = conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()
    return dict(row) if row else None


def list_scheduler_logs(conn: sqlite3.Connection, limit: int = 20) -> List[Dict[str, Any]]:
    """Retorna o histórico de execuções do agendador."""
    cursor = conn.execute(
        "SELECT * FROM scheduler_logs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def log_scheduler_run(
    conn: sqlite3.Connection,
    status: str,
    mensagem: str,
    scheduled_time: str = "08:00 America/Sao_Paulo",
) -> int:
    """Registra uma execução ou verificação do agendador."""
    cursor = conn.execute(
        """
        INSERT INTO scheduler_logs (scheduled_time, executed_at, status, mensagem)
        VALUES (?, CURRENT_TIMESTAMP, ?, ?)
        """,
        (scheduled_time, status, mensagem),
    )
    return cursor.lastrowid
