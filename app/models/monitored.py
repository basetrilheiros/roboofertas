"""
Operações para a tabela de produtos monitorados (monitored_products).
"""
import sqlite3
from typing import Any, Dict, List, Optional


def list_monitored(conn: sqlite3.Connection, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista todos os produtos monitorados com filtro opcional por status."""
    if status:
        cursor = conn.execute(
            "SELECT * FROM monitored_products WHERE status = ? ORDER BY id DESC",
            (status,),
        )
    else:
        cursor = conn.execute("SELECT * FROM monitored_products ORDER BY id DESC")
    return [dict(row) for row in cursor.fetchall()]


def get_monitored(conn: sqlite3.Connection, product_id: int) -> Optional[Dict[str, Any]]:
    """Busca um produto monitorado por ID."""
    row = conn.execute("SELECT * FROM monitored_products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None


def create_monitored(
    conn: sqlite3.Connection,
    url: str,
    titulo: str,
    categoria: str,
    preco_alvo_centavos: int,
    observacoes: str = "",
) -> int:
    """Cadastra uma nova URL de produto para monitoramento."""
    url = url.strip()
    titulo = titulo.strip()
    if not url:
        raise ValueError("A URL do produto é obrigatória.")
    if not titulo:
        raise ValueError("O título do produto é obrigatório.")
    if preco_alvo_centavos <= 0:
        raise ValueError("O preço-alvo deve ser maior que zero.")

    cursor = conn.execute(
        """
        INSERT INTO monitored_products (url, titulo, categoria, preco_alvo_centavos, observacoes, status)
        VALUES (?, ?, ?, ?, ?, 'ativo')
        """,
        (url, titulo, categoria.strip(), preco_alvo_centavos, observacoes.strip()),
    )
    product_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO audit_events (event_type, description, payload_json) VALUES (?, ?, ?)",
        (
            "product_monitored_added",
            f"Produto monitorado adicionado: {titulo}",
            f'{{"id": {product_id}, "url": "{url}", "preco_alvo": {preco_alvo_centavos}}}',
        ),
    )
    return product_id


def update_monitored(
    conn: sqlite3.Connection,
    product_id: int,
    titulo: str,
    categoria: str,
    preco_alvo_centavos: int,
    observacoes: str = "",
) -> bool:
    """Atualiza dados cadastrais de um produto monitorado."""
    titulo = titulo.strip()
    if not titulo:
        raise ValueError("O título do produto é obrigatório.")
    if preco_alvo_centavos <= 0:
        raise ValueError("O preço-alvo deve ser maior que zero.")

    cursor = conn.execute(
        """
        UPDATE monitored_products
        SET titulo = ?, categoria = ?, preco_alvo_centavos = ?, observacoes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (titulo, categoria.strip(), preco_alvo_centavos, observacoes.strip(), product_id),
    )
    return cursor.rowcount > 0


def toggle_monitored_status(conn: sqlite3.Connection, product_id: int) -> str:
    """Alterna o status entre 'ativo' e 'pausado'."""
    prod = get_monitored(conn, product_id)
    if not prod:
        raise ValueError("Produto monitorado não encontrado.")
    
    new_status = "pausado" if prod["status"] == "ativo" else "ativo"
    conn.execute(
        "UPDATE monitored_products SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, product_id),
    )
    return new_status


def delete_monitored(conn: sqlite3.Connection, product_id: int) -> bool:
    """Remove um produto monitorado."""
    prod = get_monitored(conn, product_id)
    if not prod:
        return False
    cursor = conn.execute("DELETE FROM monitored_products WHERE id = ?", (product_id,))
    conn.execute(
        "INSERT INTO audit_events (event_type, description, payload_json) VALUES (?, ?, ?)",
        (
            "product_monitored_deleted",
            f"Produto monitorado removido ID {product_id}: {prod.get('titulo')}",
            f'{{"id": {product_id}}}',
        ),
    )
    return cursor.rowcount > 0


def count_monitored(conn: sqlite3.Connection) -> Dict[str, int]:
    """Retorna contadores de produtos monitorados."""
    total = conn.execute("SELECT COUNT(*) FROM monitored_products").fetchone()[0]
    ativos = conn.execute("SELECT COUNT(*) FROM monitored_products WHERE status = 'ativo'").fetchone()[0]
    pausados = conn.execute("SELECT COUNT(*) FROM monitored_products WHERE status = 'pausado'").fetchone()[0]
    return {"total": total, "ativos": ativos, "pausados": pausados}
