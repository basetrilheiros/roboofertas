"""
Testes unitários do parser de relatórios (XLSX e texto colado).
"""
from decimal import Decimal
from pathlib import Path
import pytest

from services.parser import (
    normalize_text,
    parse_commission_rate_type,
    parse_date_transaction,
    parse_pasted_text,
    parse_price_quantity,
    parse_title_category,
    parse_xlsx,
)
from tests.conftest import SAMPLE_XLSX_PATH


def test_parser_sample_xlsx_real_file():
    """Valida o arquivo sintético 'Amostra sintetica.xlsx': 10 registros e R$ 56,70."""
    assert SAMPLE_XLSX_PATH.exists(), f"Arquivo não encontrado em {SAMPLE_XLSX_PATH}"
    
    result = parse_xlsx(SAMPLE_XLSX_PATH, confirmed_year=2026)
    
    # 1. Deve encontrar exatamente 10 registros
    assert result["total_registros_detectados"] == 10
    assert len(result["registros"]) == 10
    
    # 2. Células de erro (#VALUE!) identificadas e descartadas
    assert result["descartadas_invalidas"] >= 9
    
    # 3. Totalização exata de R$ 56,70 em centavos (5670)
    assert result["comissao_revisao_centavos"] == 5670
    assert result["comissao_revisao_formatada"] == "R$ 56,70"
    assert result["comissao_aprovada_centavos"] == 0
    assert result["comissao_paga_centavos"] == 0
    
    # 4. Todos os 10 registros devem estar com status 'EM REVISÃO'
    for reg in result["registros"]:
        assert reg["status"] == "EM REVISÃO"
        assert reg["comissao_centavos"] > 0
        assert reg["preco_unitario_centavos"] > 0


def test_parser_transaction_shared_across_multiple_products():
    """Garante que a transação 9000000000000001 tem seus 3 produtos distintos preservados."""
    result = parse_xlsx(SAMPLE_XLSX_PATH, confirmed_year=2026)
    
    shared_tx = [r for r in result["registros"] if r["transacao"] == "9000000000000001"]
    assert len(shared_tx) == 3, "Deveriam existir 3 produtos distintos com a mesma transação"
    
    # Cada um deve ter uma dedup_key distinta
    keys = {r["dedup_key"] for r in shared_tx}
    assert len(keys) == 3, "Chaves de deduplicação devem ser distintas para produtos diferentes"
    
    # Verificar lojas e produtos
    lojas = {r["loja"] for r in shared_tx}
    assert "LOJA_FICTICIA_A" in lojas
    assert "LOJA_FICTICIA_B" in lojas
    assert "LOJA_FICTICIA_C" in lojas


def test_parser_price_quantity_extraction():
    """Testa a extração precisa de valores com quantidade concatenada."""
    # Preço com vírgula e unidade colada
    cents, dec, qty, _ = parse_price_quantity("R$24,281 unidade")
    assert cents == 2428
    assert dec == Decimal("24.28")
    assert qty == 1

    cents2, dec2, qty2, _ = parse_price_quantity("R$580,531 unidade")
    assert cents2 == 58053
    assert dec2 == Decimal("580.53")
    assert qty2 == 1

    # Preço sem vírgula e unidade colada (R$ 75 e 1 unidade)
    cents3, dec3, qty3, _ = parse_price_quantity("R$751 unidade")
    assert cents3 == 7500
    assert dec3 == Decimal("75")
    assert qty3 == 1


def test_parser_commission_rate_type_extraction():
    """Testa extração de comissão, tipo de venda (direta/indireta) e taxa %."""
    cents, dec, tipo, taxa, _ = parse_commission_rate_type("R$2,39Venda direta: 12%")
    assert cents == 239
    assert dec == Decimal("2.39")
    assert tipo == "direta"
    assert taxa == 12.0

    cents2, dec2, tipo2, taxa2, _ = parse_commission_rate_type("R$1,52Venda indireta: 2.5%")
    assert cents2 == 152
    assert dec2 == Decimal("1.52")
    assert tipo2 == "indireta"
    assert taxa2 == 2.5


def test_parser_date_transaction():
    """Testa a decomposição de data sem ano e código de transação."""
    data_iso, data_texto, transacao, _ = parse_date_transaction("29/set#9000000000000002", confirmed_year=2026)
    assert data_iso == "2026-09-29"
    assert data_texto == "29/set"
    assert transacao == "9000000000000002"


def test_parser_pasted_text():
    """Testa a importação de texto colado (simulando cópia da tabela)."""
    pasted_text = """
LOJA_FICTICIA_D	R$24,281 unidade	R$2,39Venda direta: 12%	EM REVISÃO
29/set#9000000000000002
Produto fictício DCategoria: Cozinha

#VALUE!	LOJA_FICTICIA_E	R$39,901 unidade	R$5,23Venda direta: 16%	EM REVISÃO
29/set#9000000000000003
Produto fictício ECategoria: Suplementos e Shakers
"""
    result = parse_pasted_text(pasted_text, confirmed_year=2026)
    assert result["total_registros_detectados"] == 2
    assert result["comissao_revisao_centavos"] == 239 + 523
    assert result["registros"][0]["transacao"] == "9000000000000002"
    assert result["registros"][1]["transacao"] == "9000000000000003"
