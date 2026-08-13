BEGIN;

INSERT INTO conversations (
    id,
    mode,
    title,
    title_source,
    created_at,
    updated_at
)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'chat',
    '开始探索 Intelligence Hub',
    'manual',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO messages (
    id,
    conversation_id,
    role,
    mode,
    content,
    status,
    created_at
)
VALUES (
    '00000000-0000-4000-8000-000000000002',
    '00000000-0000-4000-8000-000000000001',
    'assistant',
    'chat',
    '你好，我是 Intelligence Hub。你可以从普通对话开始，也可以切换到 Work 模式调用 Agent。',
    'completed',
    CURRENT_TIMESTAMP
)
ON CONFLICT (id) DO NOTHING;

COMMIT;
