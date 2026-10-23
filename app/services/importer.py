"""
Serviço de importação e persistência com deduplicação inteligente e idempotência.
"""
from datetime import datetime
import hashlib
import sqlite3
from typing import Any, Dict, List, Optional

from database.connection import get_db
from models.audit import log_audit
from models.sales import get_status_history, update_sale_status
from services.parser import parse_pasted_text, parse_xlsx


def generate_content_hash(content_bytes_or_str: Any) -> str:
    """Gera hash SHA-256 do conteúdo para identificação única do lote."""
    if isinstance(content_bytes_or_str, str):
        data = content_bytes_or_str.encode("utf-8")
    elif isinstance(content_bytes_or_str, bytes):
        data = content_bytes_or_str
    else:
        data = str(content_bytes_or_str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def preview_import(
    conn: sqlite3.Connection,
    parsed_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compara os registros parseados com o banco de dados antes da confirmação,
    identificando novos, inalterados (duplicados) e com alteração de status.
    """
    registros_preview = []
    novos_count = 0
    atualizados_count = 0
    duplicados_count = 0

    for reg in parsed_data["registros"]:
        dedup_key = reg["dedup_key"]
        existing = conn.execute(
            "SELECT id, status, comissao_centavos, import_id FROM sales WHERE dedup_key = ?",
            (dedup_key,),
        ).fetchone()

        item_preview = dict(reg)
        if not existing:
            item_preview["action"] = "NOVO"
            item_preview["action_label"] = "Nova venda a registrar"
            novos_count += 1
        else:
            old_status = existing["status"]
            new_status = reg["status"]
            if old_status != new_status:
                item_preview["action"] = "ATUALIZAR_STATUS"
                item_preview["action_label"] = f"Alterar status de '{old_status}' para '{new_status}'"
                item_preview["old_status"] = old_status
                atualizados_count += 1
            else:
                item_preview["action"] = "DUPLICADO"
                item_preview["action_label"] = "Venda já cadastrada (idêntica, será ignorada)"
                duplicados_count += 1

        registros_preview.append(item_preview)

    preview_result = dict(parsed_data)
    preview_result["registros"] = registros_preview
    preview_result["resumo_acoes"] = {
        "novos": novos_count,
        "atualizacoes": atualizados_count,
        "duplicados": duplicados_count,
    }
    return preview_result


def execute_import(
    conn: sqlite3.Connection,
    parsed_data: Dict[str, Any],
    filename: str,
    source_type: str,
    content_hash: str,
) -> Dict[str, Any]:
    """
    Persiste os registros no SQLite com total idempotência.
    Atualiza status sem duplicar comissões.
    """
    ano_confirmado = parsed_data["ano_confirmado"]
    total_linhas = parsed_data["total_linhas_lidas"]
    total_detectados = parsed_data["total_registros_detectados"]
    descartadas = parsed_data["descartadas_invalidas"]

    # 1. Registrar entrada na tabela imports
    cursor = conn.execute(
        """
        INSERT INTO imports (
            file_hash, filename, source_type, ano_confirmado,
            total_linhas_lidas, total_registros_detectados,
            descartadas_invalidas, comissoes_revisao_centavos,
            comissoes_aprovadas_centavos, comissoes_pagas_centavos,
            comissoes_canceladas_centavos
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_hash,
            filename,
            source_type,
            ano_confirmado,
            total_linhas,
            total_detectados,
            descartadas,
            parsed_data["comissao_revisao_centavos"],
            parsed_data["comissao_aprovada_centavos"],
            parsed_data["comissao_paga_centavos"],
            parsed_data["comissao_cancelada_centavos"],
        ),
    )
    import_id = cursor.lastrowid

    novas_vendas = 0
    atualizadas = 0
    duplicadas_ignoradas = 0

    # 2. Persistir cada venda individual
    for reg in parsed_data["registros"]:
        dedup_key = reg["dedup_key"]
        existing = conn.execute(
            "SELECT id, status FROM sales WHERE dedup_key = ?",
            (dedup_key,),
        ).fetchone()

        if not existing:
            # Inserir nova venda
            conn.execute(
                """
                INSERT INTO sales (
                    dedup_key, transacao, item_id, data_venda, data_texto,
                    ano_confirmado, descricao, descricao_normalizada, categoria,
                    loja, preco_unitario_centavos, quantidade, comissao_centavos,
                    taxa_percentual, tipo_venda, status, raw_block, import_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dedup_key,
                    reg["transacao"],
                    reg.get("item_id"),
                    reg["data_venda"],
                    reg["data_texto"],
                    ano_confirmado,
                    reg["descricao"],
                    reg["descricao_normalizada"],
                    reg["categoria"],
                    reg["loja"],
                    reg["preco_unitario_centavos"],
                    reg["quantidade"],
                    reg["comissao_centavos"],
                    reg["taxa_percentual"],
                    reg["tipo_venda"],
                    reg["status"],
                    reg.get("raw_block", ""),
                    import_id,
                ),
            )
            novas_vendas += 1
        else:
            sale_id = existing["id"]
            old_status = existing["status"]
            new_status = reg["status"]

            if old_status != new_status:
                # Atualização de status auditada
                update_sale_status(
                    conn,
                    sale_id=sale_id,
                    new_status=new_status,
                    import_id=import_id,
                    observacao=f"Atualização automática via importação ({filename})",
                )
                atualizadas += 1
            else:
                # Idêntico: ignorar para não duplicar comissão
                duplicadas_ignoradas += 1

    # 3. Atualizar estatísticas consolidadas no registro da importação
    conn.execute(
        """
        UPDATE imports SET
            novas_vendas = ?,
            atualizadas = ?,
            duplicadas_ignoradas = ?
        WHERE id = ?
        """,
        (novas_vendas, atualizadas, duplicadas_ignoradas, import_id),
    )

    # 4. Registrar evento na auditoria
    log_audit(
        conn,
        "import_completed",
        f"Importação #{import_id} concluída ({filename}): {novas_vendas} novas, {atualizadas} atualizadas, {duplicadas_ignoradas} duplicadas ignoradas.",
        {
            "import_id": import_id,
            "filename": filename,
            "novas": novas_vendas,
            "atualizadas": atualizadas,
            "duplicadas": duplicadas_ignoradas,
            "total_detectados": total_detectados,
        },
    )

    return {
        "import_id": import_id,
        "filename": filename,
        "novas_vendas": novas_vendas,
        "atualizadas": atualizadas,
        "duplicadas_ignoradas": duplicadas_ignoradas,
        "descartadas_invalidas": descartadas,
        "total_detectados": total_detectados,
    }
