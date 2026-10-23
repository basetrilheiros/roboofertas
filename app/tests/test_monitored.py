"""
Testes de cadastro, pausa, edição e persistência de produtos monitorados.
"""
import pytest
import sqlite3

from database.connection import get_db
from models.monitored import (
    count_monitored,
    create_monitored,
    delete_monitored,
    get_monitored,
    list_monitored,
    toggle_monitored_status,
    update_monitored,
)


def test_monitored_crud(temp_db):
    """Testa o ciclo de vida completo de um produto monitorado."""
    with get_db(temp_db) as conn:
        # 1. Criar
        prod_id = create_monitored(
            conn,
            url="https://produto.mercadolivre.com.br/MLB-123456-barraca",
            titulo="Barraca 4 Pessoas Impermeável",
            categoria="Camping",
            preco_alvo_centavos=45000,
            observacoes="Aguardando promoção",
        )
        assert prod_id > 0

        # 2. Ler
        prod = get_monitored(conn, prod_id)
        assert prod["titulo"] == "Barraca 4 Pessoas Impermeável"
        assert prod["preco_alvo_centavos"] == 45000
        assert prod["status"] == "ativo"

        # 3. Pausar
        new_status = toggle_monitored_status(conn, prod_id)
        assert new_status == "pausado"
        assert get_monitored(conn, prod_id)["status"] == "pausado"

        # 4. Reativar
        new_status = toggle_monitored_status(conn, prod_id)
        assert new_status == "ativo"

        # 5. Atualizar
        update_monitored(conn, prod_id, "Barraca 4P Pro", "Camping", 40000, "Novo alvo")
        updated = get_monitored(conn, prod_id)
        assert updated["titulo"] == "Barraca 4P Pro"
        assert updated["preco_alvo_centavos"] == 40000

        # 6. Excluir
        assert delete_monitored(conn, prod_id) is True
        assert get_monitored(conn, prod_id) is None


def test_monitored_duplicate_url_rejected(temp_db):
    """Garante que a mesma URL não pode ser duplicada no monitoramento."""
    url = "https://produto.mercadolivre.com.br/MLB-999-isolante"
    with get_db(temp_db) as conn:
        create_monitored(conn, url, "Isolante Térmico", "Camping", 12000)
        with pytest.raises(sqlite3.IntegrityError):
            create_monitored(conn, url, "Isolante Térmico Outro", "Camping", 11000)
