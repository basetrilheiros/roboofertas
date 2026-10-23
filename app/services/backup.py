"""
Serviço de backup atômico e local do banco SQLite.
Utiliza a API oficial de backup do SQLite (compatível com WAL mode).
"""
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any, Dict, List

from config import BACKUP_DIR, DB_PATH
from database.connection import connect_db, get_db
from models.audit import log_audit


def create_backup(db_path: Path = DB_PATH, backup_dir: Path = BACKUP_DIR) -> Dict[str, Any]:
    """Cria uma cópia atômica do banco de dados SQLite com timestamp."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"basetrilheiros_backup_{timestamp}.db"
    backup_filepath = backup_dir / backup_filename

    # Executa o backup online do SQLite
    source_conn = connect_db(db_path)
    dest_conn = sqlite3.connect(str(backup_filepath))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    file_size = backup_filepath.stat().st_size

    # Registra evento na auditoria
    with get_db(db_path) as conn:
        log_audit(
            conn,
            "backup_created",
            f"Backup do banco criado com sucesso: {backup_filename} ({file_size} bytes)",
            {"filename": backup_filename, "size_bytes": file_size, "path": str(backup_filepath)},
        )

    # Limpeza preventiva: manter apenas os 10 backups mais recentes para economizar SSD
    cleanup_old_backups(backup_dir, keep=10)

    return {
        "filename": backup_filename,
        "path": str(backup_filepath),
        "size_bytes": file_size,
        "size_formatted": f"{file_size / 1024:.1f} KB",
        "created_at": timestamp,
    }


def list_backups(backup_dir: Path = BACKUP_DIR) -> List[Dict[str, Any]]:
    """Lista todos os backups existentes em ordem decrescente de data."""
    if not backup_dir.exists():
        return []

    backups = []
    for f in sorted(backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = f.stat()
        backups.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": st.st_size,
            "size_formatted": f"{st.st_size / 1024:.1f} KB",
            "modified_at": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
        })
    return backups


def cleanup_old_backups(backup_dir: Path = BACKUP_DIR, keep: int = 10) -> int:
    """Remove backups mais antigos excedentes para não esgotar o armazenamento."""
    backups = sorted(backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    if len(backups) > keep:
        for old_file in backups[keep:]:
            try:
                old_file.unlink()
                removed += 1
            except OSError:
                pass
    return removed
