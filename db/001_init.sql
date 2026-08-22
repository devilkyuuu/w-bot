CREATE TABLE IF NOT EXISTS approved_chats (
    chat_id BIGINT PRIMARY KEY,
    approved_by BIGINT NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    currency TEXT PRIMARY KEY,
    units_per_eur NUMERIC NOT NULL,
    observed_at DATE NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
