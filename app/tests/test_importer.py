"""
Testes de persistência, deduplicação inteligente e atualização de status de vendas.
"""
from database.connection import get_db
from models.sales import get_sales_summary, get_status_history, list_sales
from services.importer import execute_import, generate_content_hash, preview_import
from services.parser import parse_xlsx
from tests.conftest import SAMPLE_XLSX_PATH


def test_import_sample_file_first_time(temp_db):
    """Importa os 10 registros da planilha sintética e valida totais no SQLite."""
    parsed = parse_xlsx(SAMPLE_XLSX_PATH, confirmed_year=2026)
    
    with get_db(temp_db) as conn:
        preview = preview_import(conn, parsed)
        assert preview["resumo_acoes"]["novos"] == 10
        assert preview["resumo_acoes"]["duplicados"] == 0
        
        result = execute_import(
            conn,
            parsed_data=parsed,
            filename="Teste esportação.xlsx",
            source_type="xlsx",
            content_hash=generate_content_hash("teste1"),
        )
        
        assert result["novas_vendas"] == 10
        assert result["atualizadas"] == 0
        assert result["duplicadas_ignoradas"] == 0

        # Validação comercial via get_sales_summary
        summary = get_sales_summary(conn)
        assert summary["total_vendas"] == 10
        assert summary["em_revisao"]["count"] == 10
        assert summary["em_revisao"]["centavos"] == 5670  # R$ 56,70
        assert summary["aprovadas"]["centavos"] == 0
        assert summary["pagas"]["centavos"] == 0
        assert summary["canceladas"]["centavos"] == 0


def test_import_idempotency_no_duplicate_commissions(temp_db):
    """Garante que importar o mesmo arquivo 2 vezes NÃO duplica vendas nem comissões."""
    parsed = parse_xlsx(SAMPLE_XLSX_PATH, confirmed_year=2026)
    
    with get_db(temp_db) as conn:
        # Primeira importação
        execute_import(conn, parsed, "Teste.xlsx", "xlsx", "hash1")
        
        # Segunda importação (exatamente o mesmo lote)
        preview2 = preview_import(conn, parsed)
        assert preview2["resumo_acoes"]["novos"] == 0
        assert preview2["resumo_acoes"]["duplicados"] == 10
        
        result2 = execute_import(conn, parsed, "Teste.xlsx", "xlsx", "hash1")
        assert result2["novas_vendas"] == 0
        assert result2["atualizadas"] == 0
        assert result2["duplicadas_ignoradas"] == 10
        
        # Totais comerciais devem permanecer inalterados (R$ 56,70)
        summary = get_sales_summary(conn)
        assert summary["total_vendas"] == 10
        assert summary["em_revisao"]["centavos"] == 5670


def test_import_updates_status_with_audit_history(temp_db):
    """Garante que a transição de status (ex: EM REVISÃO -> APROVADA) é registrada no histórico."""
    parsed = parse_xlsx(SAMPLE_XLSX_PATH, confirmed_year=2026)
    
    with get_db(temp_db) as conn:
        # 1. Primeira importação
        execute_import(conn, parsed, "Teste.xlsx", "xlsx", "hash1")
        
        # 2. Simular novo lote onde o primeiro produto foi APROVADO pelo Mercado Livre
        modified_parsed = dict(parsed)
        modified_registros = [dict(r) for r in parsed["registros"]]
        modified_registros[0]["status"] = "APROVADA"
        modified_parsed["registros"] = modified_registros
        
        # Prévia deve identificar 1 atualização e 9 duplicados
        preview = preview_import(conn, modified_parsed)
        assert preview["resumo_acoes"]["atualizacoes"] == 1
        assert preview["resumo_acoes"]["duplicados"] == 9
        
        # Executar importação do lote atualizado
        result = execute_import(conn, modified_parsed, "Teste_Atualizado.xlsx", "xlsx", "hash2")
        assert result["novas_vendas"] == 0
        assert result["atualizadas"] == 1
        assert result["duplicadas_ignoradas"] == 9
        
        # Verificar no banco se a venda teve status atualizado
        first_sale = list_sales(conn, limit=10)[0]
        # O registro alterado
        sale_obj = conn.execute("SELECT * FROM sales WHERE transacao = ?", (modified_registros[0]["transacao"],)).fetchone()
        assert sale_obj["status"] == "APROVADA"
        
        # Verificar se gerou histórico em sale_status_history
        history = get_status_history(conn, sale_obj["id"])
        assert len(history) == 1
        assert history[0]["status_anterior"] == "EM REVISÃO"
        assert history[0]["status_novo"] == "APROVADA"
        
        # Comissões atualizadas no resumo comercial
        summary = get_sales_summary(conn)
        comm_aprovada_esperada = modified_registros[0]["comissao_centavos"]
        assert summary["aprovadas"]["centavos"] == comm_aprovada_esperada
        assert summary["em_revisao"]["centavos"] == 5670 - comm_aprovada_esperada
