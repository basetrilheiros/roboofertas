"""
Operações para a tabela de vendas (sales) e histórico de status.
"""
import sqlite3
from typing import Any, Dict, List, Optional


def list_sales(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    tipo: Optional[str] = None,
    categoria: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Consulta vendas com filtros flexíveis."""
    query = ["SELECT s.*, i.filename as import_filename FROM sales s LEFT JOIN imports i ON s.import_id = i.id WHERE 1=1"]
    params: List[Any] = []

    if status and status != "TODOS":
        query.append("AND s.status = ?")
        params.append(status)

    if tipo and tipo != "TODOS":
        query.append("AND s.tipo_venda = ?")
        params.append(tipo)

    if categoria and categoria != "TODAS":
        query.append("AND s.categoria = ?")
        params.append(categoria)

    if search:
        search_like = f"%{search.strip()}%"
        query.append("AND (s.descricao LIKE ? OR s.transacao LIKE ? OR s.loja LIKE ?)")
        params.extend([search_like, search_like, search_like])

    query.append("ORDER BY s.data_venda DESC, s.id DESC LIMIT ? OFFSET ?")
    params.extend([limit, offset])

    cursor = conn.execute(" ".join(query), params)
    return [dict(row) for row in cursor.fetchall()]


def get_sale(conn: sqlite3.Connection, sale_id: int) -> Optional[Dict[str, Any]]:
    """Busca uma venda por ID."""
    row = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    return dict(row) if row else None


def update_sale_status(
    conn: sqlite3.Connection,
    sale_id: int,
    new_status: str,
    import_id: Optional[int] = None,
    observacao: Optional[str] = None,
) -> bool:
    """Atualiza o status de uma venda e registra no histórico de auditoria."""
    valid_statuses = ["EM REVISÃO", "APROVADA", "PAGA", "CANCELADA"]
    new_status_clean = new_status.strip().upper()
    if new_status_clean not in valid_statuses:
        raise ValueError(f"Status inválido: {new_status}. Deve ser um de {valid_statuses}")

    sale = get_sale(conn, sale_id)
    if not sale:
        return False

    old_status = sale["status"]
    if old_status == new_status_clean:
        return True  # Sem alteração necessária

    conn.execute(
        "UPDATE sales SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status_clean, sale_id),
    )

    conn.execute(
        """
        INSERT INTO sale_status_history (sale_id, status_anterior, status_novo, import_id, observacao)
        VALUES (?, ?, ?, ?, ?)
        """,
        (sale_id, old_status, new_status_clean, import_id, observacao or "Atualização manual/importador"),
    )
    return True


def get_status_history(conn: sqlite3.Connection, sale_id: int) -> List[Dict[str, Any]]:
    """Retorna o histórico cronológico de transições de status de uma venda."""
    cursor = conn.execute(
        """
        SELECT h.*, i.filename as import_filename
        FROM sale_status_history h
        LEFT JOIN imports i ON h.import_id = i.id
        WHERE h.sale_id = ?
        ORDER BY h.changed_at DESC, h.id DESC
        """,
        (sale_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_sales_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Retorna métricas comerciais detalhadas agrupadas por status,
    garantindo que 'EM REVISÃO' seja explicitamente marcado como pendente.
    """
    summary = {
        "total_vendas": 0,
        "em_revisao": {"count": 0, "centavos": 0},
        "aprovadas": {"count": 0, "centavos": 0},
        "pagas": {"count": 0, "centavos": 0},
        "canceladas": {"count": 0, "centavos": 0},
        "por_tipo": {},
        "por_categoria": [],
    }

    # Agrupamento por status
    rows = conn.execute(
        """
        SELECT status, COUNT(*) as qtd, SUM(comissao_centavos) as total_centavos
        FROM sales
        GROUP BY status
        """
    ).fetchall()

    for r in rows:
        st = r["status"]
        qtd = r["qtd"] or 0
        cents = r["total_centavos"] or 0
        summary["total_vendas"] += qtd

        if st == "EM REVISÃO":
            summary["em_revisao"] = {"count": qtd, "centavos": cents}
        elif st == "APROVADA":
            summary["aprovadas"] = {"count": qtd, "centavos": cents}
        elif st == "PAGA":
            summary["pagas"] = {"count": qtd, "centavos": cents}
        elif st == "CANCELADA":
            summary["canceladas"] = {"count": qtd, "centavos": cents}

    # Agrupamento por tipo de venda
    tipo_rows = conn.execute(
        """
        SELECT tipo_venda, COUNT(*) as qtd, SUM(comissao_centavos) as total_centavos
        FROM sales
        GROUP BY tipo_venda
        """
    ).fetchall()
    for tr in tipo_rows:
        summary["por_tipo"][tr["tipo_venda"]] = {
            "count": tr["qtd"],
            "centavos": tr["total_centavos"] or 0,
        }

    # Agrupamento por categoria
    cat_rows = conn.execute(
        """
        SELECT COALESCE(categoria, 'Outros') as cat, COUNT(*) as qtd, SUM(comissao_centavos) as total_centavos
        FROM sales
        GROUP BY categoria
        ORDER BY total_centavos DESC
        LIMIT 10
        """
    ).fetchall()
    summary["por_categoria"] = [dict(c) for c in cat_rows]

    return summary


def list_categories(conn: sqlite3.Connection) -> List[str]:
    """Retorna lista de categorias distintas presentes nas vendas."""
    rows = conn.execute(
        "SELECT DISTINCT categoria FROM sales WHERE categoria IS NOT NULL AND categoria != '' ORDER BY categoria"
    ).fetchall()
    return [r[0] for r in rows]
