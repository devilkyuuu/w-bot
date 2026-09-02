CREATE TABLE IF NOT EXISTS disabled_media_categories (
    chat_id BIGINT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('social', 'figures')),
    PRIMARY KEY (chat_id, category),
    FOREIGN KEY (chat_id) REFERENCES approved_chats(chat_id) ON DELETE CASCADE
);
