BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    title VARCHAR(120) NOT NULL DEFAULT '新会话',
    title_source VARCHAR(20) NOT NULL DEFAULT 'default',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_conversations_title_source
        CHECK (title_source IN ('default', 'generated', 'manual'))
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL,
    role VARCHAR(20) NOT NULL,
    mode VARCHAR(20) NOT NULL DEFAULT 'chat',
    content TEXT NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_messages_conversation
        FOREIGN KEY (conversation_id)
        REFERENCES conversations (id)
        ON DELETE CASCADE,
    CONSTRAINT ck_messages_role
        CHECK (role IN ('user', 'assistant', 'system')),
    CONSTRAINT ck_messages_mode
        CHECK (mode IN ('chat', 'work')),
    CONSTRAINT ck_messages_status
        CHECK (status IN ('pending', 'streaming', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS ix_messages_conversation_id
    ON messages (conversation_id);

CREATE INDEX IF NOT EXISTS ix_messages_conversation_created_at
    ON messages (conversation_id, created_at);

COMMIT;

