-- ============================================================================
-- BASE TRILHEIROS — Esquema do Banco SQLite (Fase 1)
-- ============================================================================

PRAGMA foreign_keys = ON;

-- Parâmetros gerais do robô de curadoria e pesquisa
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    categorias_busca TEXT NOT NULL DEFAULT 'Camping, Trilhas, Sobrevivência, Pesca, Acessórios Outdoor',
    termos_busca TEXT NOT NULL DEFAULT 'barraca, saco de dormir, bota trilha, canivete, fogareiro, lanterna, isolante térmico',
    preco_min_centavos INTEGER NOT NULL DEFAULT 2000,          -- R$ 20,00
    preco_max_centavos INTEGER NOT NULL DEFAULT 150000,        -- R$ 1.500,00
    desconto_min_ativo INTEGER NOT NULL DEFAULT 0,              -- 0 = desativado por padrão
    desconto_min_percentual REAL NOT NULL DEFAULT 10.0,
    avaliacao_minima REAL NOT NULL DEFAULT 4.5,
    min_avaliacoes INTEGER NOT NULL DEFAULT 20,
    reputacao_minima TEXT NOT NULL DEFAULT 'mercado_lider_gold',
    filtro_full INTEGER NOT NULL DEFAULT 0,
    filtro_frete_gratis INTEGER NOT NULL DEFAULT 1,
    volume_anuncios_alvo INTEGER NOT NULL DEFAULT 300,         -- meta 200-500
    max_recomendacoes INTEGER NOT NULL DEFAULT 10,              -- até 10
    peso_desconto REAL NOT NULL DEFAULT 0.40,
    peso_avaliacao REAL NOT NULL DEFAULT 0.35,
    peso_frete REAL NOT NULL DEFAULT 0.25,
    diversidade_max_por_categoria INTEGER NOT NULL DEFAULT 3,
    antirrepeticao_dias INTEGER NOT NULL DEFAULT 15,
    horario_curadoria TEXT NOT NULL DEFAULT '08:00 America/Sao_Paulo',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Produtos Monitorados manualmente
CREATE TABLE IF NOT EXISTS monitored_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    titulo TEXT NOT NULL,
    categoria TEXT,
    preco_alvo_centavos INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ativo',                      -- 'ativo' | 'pausado'
    observacoes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Histórico de Importações de Relatórios
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    source_type TEXT NOT NULL,                                 -- 'xlsx' | 'paste'
    ano_confirmado INTEGER NOT NULL,
    total_linhas_lidas INTEGER NOT NULL DEFAULT 0,
    total_registros_detectados INTEGER NOT NULL DEFAULT 0,
    novas_vendas INTEGER NOT NULL DEFAULT 0,
    atualizadas INTEGER NOT NULL DEFAULT 0,
    duplicadas_ignoradas INTEGER NOT NULL DEFAULT 0,
    descartadas_invalidas INTEGER NOT NULL DEFAULT 0,
    comissoes_revisao_centavos INTEGER NOT NULL DEFAULT 0,
    comissoes_aprovadas_centavos INTEGER NOT NULL DEFAULT 0,
    comissoes_pagas_centavos INTEGER NOT NULL DEFAULT 0,
    comissoes_canceladas_centavos INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Vendas de Afiliados
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT NOT NULL UNIQUE,
    transacao TEXT NOT NULL,
    item_id TEXT,
    data_venda TEXT NOT NULL,                                  -- YYYY-MM-DD
    data_texto TEXT NOT NULL,                                  -- ex: '29/set'
    ano_confirmado INTEGER NOT NULL,
    descricao TEXT NOT NULL,
    descricao_normalizada TEXT NOT NULL,
    categoria TEXT,
    loja TEXT,
    preco_unitario_centavos INTEGER NOT NULL,
    quantidade INTEGER NOT NULL DEFAULT 1,
    comissao_centavos INTEGER NOT NULL,
    taxa_percentual REAL,
    tipo_venda TEXT NOT NULL,                                  -- 'direta' | 'indireta'
    status TEXT NOT NULL DEFAULT 'EM REVISÃO',                 -- 'EM REVISÃO' | 'APROVADA' | 'PAGA' | 'CANCELADA'
    raw_block TEXT,
    import_id INTEGER REFERENCES imports(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Histórico de Alterações de Status das Vendas
CREATE TABLE IF NOT EXISTS sale_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    status_anterior TEXT NOT NULL,
    status_novo TEXT NOT NULL,
    import_id INTEGER REFERENCES imports(id),
    observacao TEXT,
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Trilha de Auditoria
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    payload_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Log do Agendador (preparação de execuções às 08:00 e aviso de execuções perdidas)
CREATE TABLE IF NOT EXISTS scheduler_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_time TEXT NOT NULL DEFAULT '08:00 America/Sao_Paulo',
    executed_at TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'pendente',                    -- 'pendente' | 'executado' | 'perdido' | 'manual'
    mensagem TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Índices para buscas rápidas locais
CREATE INDEX IF NOT EXISTS idx_sales_transacao ON sales(transacao);
CREATE INDEX IF NOT EXISTS idx_sales_status ON sales(status);
CREATE INDEX IF NOT EXISTS idx_sales_data_venda ON sales(data_venda);
CREATE INDEX IF NOT EXISTS idx_sales_tipo ON sales(tipo_venda);
CREATE INDEX IF NOT EXISTS idx_monitored_status ON monitored_products(status);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_status_history_sale_id ON sale_status_history(sale_id);

-- Inserção de parâmetros padrão caso não existam
INSERT OR IGNORE INTO settings (id) VALUES (1);
