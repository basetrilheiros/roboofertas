-- ============================================================================
-- BASE TRILHEIROS — Migração Incremental Fase 2 (0002_phase2_discovery_and_prices)
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1. Credenciais e tokens da API do Mercado Livre (armazenamento criptografado em repouso)
CREATE TABLE IF NOT EXISTS ml_credentials (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    client_id TEXT,
    client_secret_encrypted TEXT,
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at TIMESTAMP,
    redirect_uri TEXT NOT NULL DEFAULT 'http://127.0.0.1:5000/ml/callback',
    status TEXT NOT NULL DEFAULT 'desconectado',            -- 'desconectado' | 'autorizado' | 'expirado' | 'erro'
    last_error TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO ml_credentials (id) VALUES (1);

-- 2. Histórico de execuções do robô de pesquisa e análise
CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type TEXT NOT NULL DEFAULT 'manual',           -- 'agendado_08h' | 'manual'
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'em_andamento',           -- 'em_andamento' | 'sucesso' | 'falha' | 'interrompido'
    total_consultados INTEGER NOT NULL DEFAULT 0,
    aprovados_filtros INTEGER NOT NULL DEFAULT 0,
    rejeitados_filtros INTEGER NOT NULL DEFAULT 0,
    ofertas_geradas INTEGER NOT NULL DEFAULT 0,
    erros_json TEXT
);

-- 3. Catálogo de produtos descobertos
CREATE TABLE IF NOT EXISTS discovered_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ml_item_id TEXT NOT NULL UNIQUE,                       -- ex: MLB123456789
    title TEXT NOT NULL,
    category_id TEXT,
    category_name TEXT,
    permalink TEXT NOT NULL,
    thumbnail_url TEXT,
    seller_id INTEGER,
    seller_nickname TEXT,
    seller_reputation TEXT,
    is_full INTEGER NOT NULL DEFAULT 0,
    free_shipping INTEGER NOT NULL DEFAULT 0,
    rating_average REAL,
    rating_total INTEGER,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. Observatório de Histórico de Preços (alimentado dia a dia)
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ml_item_id TEXT NOT NULL,
    monitored_product_id INTEGER REFERENCES monitored_products(id) ON DELETE SET NULL,
    price_centavos INTEGER NOT NULL,
    original_price_centavos INTEGER,
    observed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL DEFAULT 'api_search'              -- 'api_search' | 'api_item' | 'monitored_check' | 'simulado'
);

-- 5. Ofertas Curadas para decisão humana
CREATE TABLE IF NOT EXISTS curated_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES discovery_runs(id),
    ml_item_id TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    score_breakdown_json TEXT,
    justificativa TEXT NOT NULL,
    preco_momento_centavos INTEGER NOT NULL,
    menor_preco_historico_centavos INTEGER,
    maior_preco_historico_centavos INTEGER,
    dias_historico_disponiveis INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pendente',                -- 'pendente' | 'aprovada' | 'rejeitada'
    motivo_rejeicao TEXT,
    rejection_notes TEXT,
    affiliate_link TEXT,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6. Registro de feedback das decisões do usuário (para calibragem transparente)
CREATE TABLE IF NOT EXISTS user_decisions_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name TEXT,
    seller_nickname TEXT,
    price_range TEXT,
    decision TEXT NOT NULL,                                -- 'aprovada' | 'rejeitada'
    reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Índices de consulta rápida
CREATE INDEX IF NOT EXISTS idx_price_history_item ON price_history(ml_item_id);
CREATE INDEX IF NOT EXISTS idx_price_history_monitored ON price_history(monitored_product_id);
CREATE INDEX IF NOT EXISTS idx_price_history_observed ON price_history(observed_at);
CREATE INDEX IF NOT EXISTS idx_discovered_ml_item_id ON discovered_products(ml_item_id);
CREATE INDEX IF NOT EXISTS idx_curated_offers_status ON curated_offers(status);
