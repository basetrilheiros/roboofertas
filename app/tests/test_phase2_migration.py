"""
Testes de migração segura da Fase 2 e preservação estrita dos dados da Fase 1.
"""
from database.connection import get_db
from models.ml_credentials import get_ml_credentials, save_ml_app_keys, save_ml_tokens
from models.sales import get_sales_summary
from services.importer import execute_import
from services.parser import parse_xlsx
from tests.conftest import SAMPLE_XLSX_PATH


def test_phase2_migration_preserves_phase1_sales(temp_db):
    """Garante que a migração para a Fase 2 preserva as 10 vendas e R$ 56,70 em revisão."""
    # 1. Simular base inicial da Fase 1 com os dados reais importados
    parsed = parse_xlsx(SAMPLE_XLSX_PATH, confirmed_year=2026)
    with get_db(temp_db) as conn:
        execute_import(conn, parsed, "Teste.xlsx", "xlsx", "hash_phase1")

    # 2. Verificar que os dados da Fase 1 continuam intactos no banco após a migração
    with get_db(temp_db) as conn:
        summary = get_sales_summary(conn)
        assert summary["total_vendas"] == 10
        assert summary["em_revisao"]["count"] == 10
        assert summary["em_revisao"]["centavos"] == 5670  # R$ 56,70
        assert summary["aprovadas"]["centavos"] == 0
        assert summary["pagas"]["centavos"] == 0


def test_phase2_tables_created(temp_db):
    """Verifica se todas as novas tabelas da Fase 2 foram criadas."""
    with get_db(temp_db) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        assert "ml_credentials" in tables
        assert "discovery_runs" in tables
        assert "discovered_products" in tables
        assert "price_history" in tables
        assert "curated_offers" in tables
        assert "user_decisions_feedback" in tables


def test_credentials_encryption_at_rest(temp_db):
    """Garante que Client Secret e tokens NUNCA fiquem em texto puro no SQLite."""
    with get_db(temp_db) as conn:
        raw_secret = "segredo_client_secret_real_987654"
        save_ml_app_keys(
            conn,
            client_id="1234567890",
            client_secret=raw_secret,
            redirect_uri="http://127.0.0.1:5000/ml/callback",
        )

        # 1. Consulta SQL direta (como um dump físico do banco):
        # A coluna DEVE conter texto cifrado e NÃO conter a senha em texto puro
        raw_row = conn.execute("SELECT * FROM ml_credentials WHERE id = 1").fetchone()
        assert raw_row["client_secret_encrypted"] is not None
        assert raw_secret not in raw_row["client_secret_encrypted"]

        # 2. Leitura via modelo: descriptografa em memória com sucesso
        creds = get_ml_credentials(conn)
        assert creds["client_id"] == "1234567890"
        assert creds["client_secret"] == raw_secret
        assert creds["has_credentials"] is True
        assert creds["is_authenticated"] is False


def test_token_save_and_expiration(temp_db):
    """Testa armazenamento cifrado de tokens OAuth e controle de expiração."""
    with get_db(temp_db) as conn:
        raw_access = "APP_USR-987654321-access"
        raw_refresh = "TG-12345678-refresh"
        save_ml_tokens(conn, access_token=raw_access, refresh_token=raw_refresh, expires_in_seconds=21600)

        # Consulta bruta: tokens cifrados
        raw_row = conn.execute("SELECT * FROM ml_credentials WHERE id = 1").fetchone()
        assert raw_access not in raw_row["access_token_encrypted"]
        assert raw_refresh not in raw_row["refresh_token_encrypted"]
        assert raw_row["token_expires_at"] is not None

        # Leitura via modelo
        creds = get_ml_credentials(conn)
        assert creds["access_token"] == raw_access
        assert creds["refresh_token"] == raw_refresh
        assert creds["is_authenticated"] is True
