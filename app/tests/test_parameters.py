"""
Testes de persistência e validação dos parâmetros de curadoria e pesquisa.
"""
import pytest

from database.connection import get_db
from models.settings import get_settings, update_settings


def test_default_settings_exist(temp_db):
    """Verifica se os parâmetros padrão são inicializados corretamente."""
    with get_db(temp_db) as conn:
        settings = get_settings(conn)
        assert settings["horario_curadoria"] == "08:00 America/Sao_Paulo"
        assert settings["preco_min_centavos"] == 2000  # R$ 20,00
        assert settings["preco_max_centavos"] == 150000  # R$ 1.500,00
        assert settings["desconto_min_ativo"] == 0  # Desativado por padrão conforme Prompt Mestre
        assert settings["avaliacao_minima"] == 4.5
        assert settings["min_avaliacoes"] == 20
        assert settings["max_recomendacoes"] == 10
        assert settings["volume_anuncios_alvo"] == 300


def test_update_settings_and_persistence(temp_db):
    """Testa atualização de parâmetros e garante que persistem após fechar conexão."""
    with get_db(temp_db) as conn:
        update_settings(
            conn,
            {
                "categorias_busca": "Trekking, Escalada",
                "termos_busca": "corda dinamica, mosquetão, bota impermeável",
                "preco_min_centavos": 5000,
                "preco_max_centavos": 200000,
                "desconto_min_ativo": 1,
                "desconto_min_percentual": 15.0,
                "avaliacao_minima": 4.8,
                "min_avaliacoes": 50,
                "reputacao_minima": "mercado_lider_platinum",
                "filtro_full": 1,
                "filtro_frete_gratis": 1,
                "volume_anuncios_alvo": 450,
                "max_recomendacoes": 8,
                "peso_desconto": 0.50,
                "peso_avaliacao": 0.30,
                "peso_frete": 0.20,
                "diversidade_max_por_categoria": 2,
                "antirrepeticao_dias": 20,
                "horario_curadoria": "08:00 America/Sao_Paulo",
            },
        )

    # Reabrir o banco de dados e validar persistência
    with get_db(temp_db) as conn:
        reloaded = get_settings(conn)
        assert reloaded["categorias_busca"] == "Trekking, Escalada"
        assert reloaded["preco_min_centavos"] == 5000
        assert reloaded["preco_max_centavos"] == 200000
        assert reloaded["desconto_min_ativo"] == 1
        assert reloaded["desconto_min_percentual"] == 15.0
        assert reloaded["avaliacao_minima"] == 4.8
        assert reloaded["volume_anuncios_alvo"] == 450
        assert reloaded["max_recomendacoes"] == 8


def test_invalid_settings_validation(temp_db):
    """Valida que entradas incoerentes geram erro explícito."""
    with get_db(temp_db) as conn:
        # Preço min > Preço max
        with pytest.raises(ValueError, match="preço mínimo não pode ser maior"):
            update_settings(conn, {"preco_min_centavos": 10000, "preco_max_centavos": 5000})

        # Avaliação fora de 1 a 5
        with pytest.raises(ValueError, match="Avaliação mínima deve estar entre 1.0 e 5.0"):
            update_settings(conn, {"avaliacao_minima": 6.0})

        # Número de avaliações negativo
        with pytest.raises(ValueError, match="Número mínimo de avaliações não pode ser negativo"):
            update_settings(conn, {"min_avaliacoes": -5})
