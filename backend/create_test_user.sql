INSERT INTO "user" (id, email, password_hash, full_name, role, faculty_id, is_active, created_at, updated_at)
VALUES (
    'test-faculty-001',
    'test@faculty.edu',
    '$argon2id$v=19$m=65536,t=2,p=2$ndG77HJvobii3W4g7ZEzVA$rIAT4fjZQvf5OsPvHFL+/5E3XeEXuNormZ0po0uEgFE',
    'Test Faculty',
    'faculty',
    'FAC001',
    TRUE,
    NOW(),
    NOW()
) ON CONFLICT (id) DO UPDATE SET 
    email = EXCLUDED.email,
    full_name = EXCLUDED.full_name,
    role = EXCLUDED.role,
    faculty_id = EXCLUDED.faculty_id,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();