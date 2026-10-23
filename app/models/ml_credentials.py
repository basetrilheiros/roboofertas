"""
Modelo de acesso e armazenamento seguro para credenciais do Mercado Livre.
Garante que Client Secret, Access Token e Refresh Token NUNCA sejam persistidos em texto puro.
"""
from datetime import datetime
import sqlite3
from typing import Any, Dict, Optional

from services.crypto import decrypt_secret, encrypt_secret


def get_ml_credentials(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Retorna as credenciais e status de autenticação (com segredos descriptografados em memória)."""
    row = conn.execute("SELECT * FROM ml_credentials WHERE id = 1").fetchone()
    if not row:
        conn.execute("INSERT OR IGNORE INTO ml_credentials (id) VALUES (1);")
        row = conn.execute("SELECT * FROM ml_credentials WHERE id = 1").fetchone()

    data = dict(row)
    # Descriptografar campos sensíveis
    data["client_secret"] = decrypt_secret(data.get("client_secret_encrypted"))
    data["access_token"] = decrypt_secret(data.get("access_token_encrypted"))
    data["refresh_token"] = decrypt_secret(data.get("refresh_token_encrypted"))
    
    # Campo booleano de conveniência
    data["has_credentials"] = bool(data.get("client_id") and data.get("client_secret"))
    data["is_authenticated"] = bool(data.get("access_token") and data.get("status") == "autorizado")

    return data


def save_ml_app_keys(
    conn: sqlite3.Connection,
    client_id: str,
    client_secret: str,
    redirect_uri: str = "http://127.0.0.1:5000/ml/callback",
) -> None:
    """Salva App ID e Client Secret (criptografado em repouso)."""
    client_id_clean = client_id.strip() if client_id else ""
    client_secret_clean = client_secret.strip() if client_secret else ""
    secret_enc = encrypt_secret(client_secret_clean) if client_secret_clean else None

    conn.execute(
        """
        UPDATE ml_credentials SET
            client_id = ?,
            client_secret_encrypted = ?,
            redirect_uri = ?,
            status = 'desconectado',
            last_error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (client_id_clean, secret_enc, redirect_uri.strip()),
    )


def save_ml_tokens(
    conn: sqlite3.Connection,
    access_token: str,
    refresh_token: str,
    expires_in_seconds: int,
) -> None:
    """Salva tokens OAuth recebidos (criptografados em repouso) e calcula timestamp de expiração."""
    access_enc = encrypt_secret(access_token)
    refresh_enc = encrypt_secret(refresh_token)
    
    expires_at = datetime.fromtimestamp(datetime.now().timestamp() + max(0, expires_in_seconds - 60))

    conn.execute(
        """
        UPDATE ml_credentials SET
            access_token_encrypted = ?,
            refresh_token_encrypted = ?,
            token_expires_at = ?,
            status = 'autorizado',
            last_error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (access_enc, refresh_enc, expires_at.strftime("%Y-%m-%d %H:%M:%S")),
    )


def mark_ml_auth_error(conn: sqlite3.Connection, error_msg: str) -> None:
    """Registra falha de autenticação ou token expirado/revogado."""
    conn.execute(
        """
        UPDATE ml_credentials SET
            status = 'erro',
            last_error = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (error_msg,),
    )
