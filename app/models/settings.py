"""
Modelo e operações para a tabela de parâmetros (settings).
"""
import json
import sqlite3
from typing import Any, Dict, Optional


def get_settings(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Retorna o registro único de configurações com valores tipados."""
    row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    if not row:
        conn.execute("INSERT OR IGNORE INTO settings (id) VALUES (1);")
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    return dict(row)


def update_settings(conn: sqlite3.Connection, data: Dict[str, Any]) -> Dict[str, Any]:
    """Valida e persiste as configurações no SQLite."""
    # Validações
    preco_min = int(data.get("preco_min_centavos", 2000))
    preco_max = int(data.get("preco_max_centavos", 150000))
    if preco_min < 0 or preco_max <= 0:
        raise ValueError("Faixa de preço deve conter valores positivos.")
    if preco_min > preco_max:
        raise ValueError("O preço mínimo não pode ser maior que o preço máximo.")

    avaliacao_minima = float(data.get("avaliacao_minima", 4.5))
    if not (1.0 <= avaliacao_minima <= 5.0):
        raise ValueError("Avaliação mínima deve estar entre 1.0 e 5.0.")

    min_avaliacoes = int(data.get("min_avaliacoes", 20))
    if min_avaliacoes < 0:
        raise ValueError("Número mínimo de avaliações não pode ser negativo.")

    desconto_min_ativo = 1 if data.get("desconto_min_ativo") in [1, True, "1", "true", "on"] else 0
    desconto_min_percentual = float(data.get("desconto_min_percentual", 10.0))
    if desconto_min_percentual < 0 or desconto_min_percentual > 100:
        raise ValueError("Desconto mínimo deve estar entre 0% e 100%.")

    peso_desconto = float(data.get("peso_desconto", 0.40))
    peso_avaliacao = float(data.get("peso_avaliacao", 0.35))
    peso_frete = float(data.get("peso_frete", 0.25))

    max_recomendacoes = int(data.get("max_recomendacoes", 10))
    if not (1 <= max_recomendacoes <= 50):
        raise ValueError("Máximo de recomendações deve estar entre 1 e 50.")

    volume_anuncios = int(data.get("volume_anuncios_alvo", 300))
    if volume_anuncios < 10:
        raise ValueError("Volume de anúncios pretendido deve ser de pelo menos 10.")

    filtro_full = 1 if data.get("filtro_full") in [1, True, "1", "true", "on"] else 0
    filtro_frete_gratis = 1 if data.get("filtro_frete_gratis") in [1, True, "1", "true", "on"] else 0

    categorias_busca = str(data.get("categorias_busca", "")).strip()
    termos_busca = str(data.get("termos_busca", "")).strip()
    reputacao_minima = str(data.get("reputacao_minima", "mercado_lider_gold")).strip()
    diversidade_max = int(data.get("diversidade_max_por_categoria", 3))
    antirrepeticao_dias = int(data.get("antirrepeticao_dias", 15))
    horario_curadoria = str(data.get("horario_curadoria", "08:00 America/Sao_Paulo")).strip()

    conn.execute(
        """
        UPDATE settings SET
            categorias_busca = ?,
            termos_busca = ?,
            preco_min_centavos = ?,
            preco_max_centavos = ?,
            desconto_min_ativo = ?,
            desconto_min_percentual = ?,
            avaliacao_minima = ?,
            min_avaliacoes = ?,
            reputacao_minima = ?,
            filtro_full = ?,
            filtro_frete_gratis = ?,
            volume_anuncios_alvo = ?,
            max_recomendacoes = ?,
            peso_desconto = ?,
            peso_avaliacao = ?,
            peso_frete = ?,
            diversidade_max_por_categoria = ?,
            antirrepeticao_dias = ?,
            horario_curadoria = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (
            categorias_busca,
            termos_busca,
            preco_min,
            preco_max,
            desconto_min_ativo,
            desconto_min_percentual,
            avaliacao_minima,
            min_avaliacoes,
            reputacao_minima,
            filtro_full,
            filtro_frete_gratis,
            volume_anuncios,
            max_recomendacoes,
            peso_desconto,
            peso_avaliacao,
            peso_frete,
            diversidade_max,
            antirrepeticao_dias,
            horario_curadoria,
        ),
    )

    # Registro na auditoria
    conn.execute(
        "INSERT INTO audit_events (event_type, description, payload_json) VALUES (?, ?, ?)",
        (
            "settings_updated",
            "Parâmetros de curadoria e pesquisa atualizados.",
            json.dumps(data, ensure_ascii=False),
        ),
    )

    return get_settings(conn)
