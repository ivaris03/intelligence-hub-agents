BEGIN;

INSERT INTO users (id, phone, password_hash, display_name, role, is_active)
VALUES (
    '10000000-0000-4000-8000-000000000000',
    '13900000001',
    'pbkdf2_sha256$600000$aW50ZWxodWItc2VlZC12MQ$tNPkEEFOw0P3gDzM_JbTAQWlxiRjVSuCM3dvdOc_XSk',
    '管理员',
    'admin',
    TRUE
)
ON CONFLICT (phone) DO NOTHING;

INSERT INTO users (id, phone, password_hash, display_name, role, is_active)
SELECT
    ('10000000-0000-4000-8000-' || lpad(seed::text, 12, '0'))::uuid,
    '137000000' || lpad(seed::text, 2, '0'),
    'pbkdf2_sha256$600000$aW50ZWxodWItc2VlZC12MQ$tNPkEEFOw0P3gDzM_JbTAQWlxiRjVSuCM3dvdOc_XSk',
    '用户' || lpad(seed::text, 2, '0'),
    'member',
    TRUE
FROM generate_series(1, 20) AS seed
ON CONFLICT (phone) DO NOTHING;

INSERT INTO app_settings (user_id)
VALUES ('10000000-0000-4000-8000-000000000000')
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO memory_summaries (user_id, content, source)
VALUES ('10000000-0000-4000-8000-000000000000', '', 'manual')
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO conversations (
    id,
    user_id,
    mode,
    title,
    title_source,
    created_at,
    updated_at
)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000000',
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
