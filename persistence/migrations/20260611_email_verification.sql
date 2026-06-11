DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'is_verified'
    ) THEN
        ALTER TABLE users
        ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT FALSE;

        -- Existing accounts predate email verification; keep them usable.
        UPDATE users
        SET is_verified = TRUE,
            updated_at = now();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'verification_token'
    ) THEN
        ALTER TABLE users
        ADD COLUMN verification_token UUID;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS users_verification_token_unique
ON users(verification_token)
WHERE verification_token IS NOT NULL;
