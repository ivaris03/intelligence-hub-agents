-- Intelligence Hub MVP reference schema for a brand-new PostgreSQL database.
-- Alembic is the canonical migration path; do not run this after `alembic upgrade`.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id UUID PRIMARY KEY,
    phone VARCHAR(11) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(80) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE conversations (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    mode VARCHAR(20) NOT NULL DEFAULT 'chat' CHECK (mode IN ('chat', 'work')),
    title VARCHAR(120) NOT NULL DEFAULT '新会话',
    title_source VARCHAR(20) NOT NULL DEFAULT 'default'
        CHECK (title_source IN ('default', 'generated', 'manual')),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    memory_cursor TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE skills (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    normalized_name VARCHAR(80) NOT NULL,
    description VARCHAR(500) NOT NULL DEFAULT '',
    instructions TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, normalized_name)
);

CREATE TABLE skill_snapshots (
    id UUID PRIMARY KEY,
    skill_id UUID REFERENCES skills (id) ON DELETE SET NULL,
    name VARCHAR(80) NOT NULL,
    description VARCHAR(500) NOT NULL DEFAULT '',
    instructions TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE app_settings (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    memory_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    web_search_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    appearance VARCHAR(20) NOT NULL DEFAULT 'system'
        CHECK (appearance IN ('system', 'light', 'dark')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE memory_summaries (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    content TEXT NOT NULL DEFAULT '',
    source VARCHAR(20) NOT NULL DEFAULT 'manual'
        CHECK (source IN ('manual', 'explicit', 'automatic')),
    source_conversation_id UUID REFERENCES conversations (id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE memory_chat_messages (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    memory_changed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pending_memory_conversations (
    conversation_id UUID PRIMARY KEY REFERENCES conversations (id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    through_at TIMESTAMPTZ NOT NULL,
    process_after TIMESTAMPTZ NOT NULL,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE files (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('document', 'image')),
    size BIGINT NOT NULL CHECK (size >= 0),
    storage_key VARCHAR(500) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'processing'
        CHECK (status IN ('processing', 'ready', 'failed')),
    error VARCHAR(500),
    text_content TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE file_chunks (
    id UUID PRIMARY KEY,
    file_id UUID NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    locator VARCHAR(255) NOT NULL,
    embedding VECTOR(1024),
    UNIQUE (file_id, chunk_index)
);

CREATE TABLE agent_runs (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    agent_type VARCHAR(20) NOT NULL CHECK (agent_type IN ('image', 'slides', 'research')),
    intent VARCHAR(20) NOT NULL DEFAULT 'CREATE'
        CHECK (intent IN ('CREATE', 'MODIFY', 'RESUME')),
    source_run_id UUID REFERENCES agent_runs (id) ON DELETE SET NULL,
    source_artifact_id UUID,
    skill_snapshot_id UUID REFERENCES skill_snapshots (id) ON DELETE SET NULL,
    input TEXT NOT NULL,
    stage VARCHAR(50) NOT NULL DEFAULT 'queued',
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    answer TEXT NOT NULL DEFAULT '',
    public_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    error VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    mode VARCHAR(20) NOT NULL DEFAULT 'chat' CHECK (mode IN ('chat', 'work')),
    agent_type VARCHAR(20),
    skill_snapshot_id UUID REFERENCES skill_snapshots (id) ON DELETE SET NULL,
    run_id UUID,
    regenerated_from_id UUID REFERENCES messages (id) ON DELETE SET NULL,
    content TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    follow_up TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'streaming', 'completed', 'failed', 'cancelled')),
    error VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE message_parts (
    id UUID PRIMARY KEY,
    message_id UUID NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    type VARCHAR(40) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (message_id, seq)
);

CREATE TABLE message_skills (
    message_id UUID NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    skill_snapshot_id UUID NOT NULL REFERENCES skill_snapshots (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY (message_id, skill_snapshot_id),
    UNIQUE (message_id, position)
);

CREATE TABLE tool_calls (
    id UUID PRIMARY KEY,
    message_id UUID REFERENCES messages (id) ON DELETE CASCADE,
    run_id UUID REFERENCES agent_runs (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL DEFAULT 0,
    tool_name VARCHAR(100) NOT NULL,
    input_summary TEXT NOT NULL DEFAULT '',
    output_summary TEXT NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'preparing',
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((message_id IS NOT NULL) <> (run_id IS NOT NULL))
);

CREATE TABLE message_files (
    message_id UUID NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    file_id UUID NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    purpose VARCHAR(30) NOT NULL DEFAULT 'context',
    PRIMARY KEY (message_id, file_id)
);

CREATE TABLE run_files (
    run_id UUID NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    file_id UUID NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    purpose VARCHAR(30) NOT NULL DEFAULT 'input',
    PRIMARY KEY (run_id, file_id)
);

CREATE TABLE run_events (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, seq)
);

CREATE TABLE run_checkpoints (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    stage VARCHAR(50) NOT NULL,
    checkpoint_id VARCHAR(100) NOT NULL,
    input_hash VARCHAR(64) NOT NULL,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, checkpoint_id)
);

CREATE TABLE artifacts (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    parent_artifact_id UUID REFERENCES artifacts (id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    type VARCHAR(20) NOT NULL CHECK (type IN ('image', 'pptx', 'markdown')),
    name VARCHAR(255) NOT NULL,
    storage_key VARCHAR(500) NOT NULL UNIQUE,
    mime_type VARCHAR(100) NOT NULL,
    size BIGINT NOT NULL CHECK (size >= 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, type, version)
);

ALTER TABLE agent_runs
    ADD CONSTRAINT fk_agent_runs_source_artifact
    FOREIGN KEY (source_artifact_id) REFERENCES artifacts (id) ON DELETE SET NULL;

ALTER TABLE messages
    ADD CONSTRAINT fk_messages_run
    FOREIGN KEY (run_id) REFERENCES agent_runs (id) ON DELETE SET NULL;

CREATE INDEX ix_conversations_last_activity_at ON conversations (last_activity_at);
CREATE INDEX ix_conversations_user_id ON conversations (user_id);
CREATE INDEX ix_skills_user_id ON skills (user_id);
CREATE INDEX ix_skill_snapshots_skill_id ON skill_snapshots (skill_id);
CREATE INDEX ix_skill_snapshots_content_hash ON skill_snapshots (content_hash);
CREATE INDEX ix_memory_summaries_source_conversation_id
    ON memory_summaries (source_conversation_id);
CREATE INDEX ix_memory_chat_messages_user_id
    ON memory_chat_messages (user_id);
CREATE INDEX ix_memory_chat_messages_created_at
    ON memory_chat_messages (created_at);
CREATE INDEX ix_pending_memory_conversations_user_id
    ON pending_memory_conversations (user_id);
CREATE INDEX ix_pending_memory_conversations_process_after
    ON pending_memory_conversations (process_after);
CREATE INDEX ix_files_conversation_id ON files (conversation_id);
CREATE INDEX ix_files_created_at ON files (created_at);
CREATE INDEX ix_file_chunks_file_id ON file_chunks (file_id);
CREATE INDEX ix_messages_conversation_created_at ON messages (conversation_id, created_at);
CREATE INDEX ix_messages_skill_snapshot_id ON messages (skill_snapshot_id);
CREATE INDEX ix_messages_run_id ON messages (run_id);
CREATE INDEX ix_messages_regenerated_from_id ON messages (regenerated_from_id);
CREATE INDEX ix_message_parts_message_id ON message_parts (message_id);
CREATE INDEX ix_tool_calls_message_id ON tool_calls (message_id);
CREATE INDEX ix_tool_calls_run_id ON tool_calls (run_id);
CREATE INDEX ix_agent_runs_conversation_created_at ON agent_runs (conversation_id, created_at);
CREATE INDEX ix_agent_runs_agent_type ON agent_runs (agent_type);
CREATE INDEX ix_agent_runs_status ON agent_runs (status);
CREATE INDEX ix_agent_runs_source_run_id ON agent_runs (source_run_id);
CREATE INDEX ix_agent_runs_source_artifact_id ON agent_runs (source_artifact_id);
CREATE INDEX ix_agent_runs_skill_snapshot_id ON agent_runs (skill_snapshot_id);
CREATE INDEX ix_run_events_run_id ON run_events (run_id);
CREATE INDEX ix_run_checkpoints_run_id ON run_checkpoints (run_id);
CREATE INDEX ix_run_checkpoints_input_hash ON run_checkpoints (input_hash);
CREATE INDEX ix_run_checkpoints_created_at ON run_checkpoints (created_at);
CREATE INDEX ix_artifacts_run_id ON artifacts (run_id);
CREATE INDEX ix_artifacts_parent_artifact_id ON artifacts (parent_artifact_id);
CREATE INDEX ix_artifacts_created_at ON artifacts (created_at);

COMMIT;
