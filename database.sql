CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(120) NOT NULL,
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('entrada', 'saida')),
    valor NUMERIC(14, 2) NOT NULL CHECK (valor > 0),
    descricao TEXT NOT NULL,
    categoria VARCHAR(120) NOT NULL DEFAULT 'geral',
    data_transacao TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    moeda_original VARCHAR(3) NOT NULL DEFAULT 'BRL',
    valor_original NUMERIC(14, 2),
    taxa_cambio NUMERIC(18, 8),
    data_cotacao DATE,
    fonte_cotacao VARCHAR(120)
);

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS moeda_original VARCHAR(3) NOT NULL DEFAULT 'BRL';
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS valor_original NUMERIC(14, 2);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS taxa_cambio NUMERIC(18, 8);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS data_cotacao DATE;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS fonte_cotacao VARCHAR(120);

CREATE INDEX IF NOT EXISTS idx_transactions_user_date
    ON transactions (user_id, data_transacao DESC);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(120) NOT NULL,
    titulo VARCHAR(240) NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    inicio TIMESTAMPTZ NOT NULL,
    fim TIMESTAMPTZ NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_event_fim CHECK (fim >= inicio)
);

CREATE INDEX IF NOT EXISTS idx_events_user_start
    ON events (user_id, inicio ASC);

CREATE TABLE IF NOT EXISTS escritas_turno (
    turno_id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(120) NOT NULL,
    user_id VARCHAR(120) NOT NULL,
    resultados JSONB NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
