-- 0014 M1 round-3 (V-38): the review sign-in page's pre-session double-submit token is enforced
-- server-side. Every issued token is stored as its SHA-256 digest (never the clear value) with a
-- server-clock expiry; redeeming consumes the row atomically, so a replayed (cookie, form) pair
-- signs in exactly once, a renewal after a failed attempt invalidates the token before it, and the
-- TTL no longer rests on the cookie's Max-Age. Lifecycle is append + one consume, like the other
-- credential tables: the whole-schema deletion guard applies and old rows simply expire.
CREATE TABLE login_tokens (
  id          uuid PRIMARY KEY,
  token_hash  text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  consumed_at timestamptz,
  CHECK (expires_at > created_at),
  CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);

-- Whole-schema guards (migrations/README.md rule 0): the deletion and float classes keep
-- covering every table.
CREATE TRIGGER login_tokens_no_delete BEFORE DELETE ON login_tokens
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER login_tokens_no_truncate BEFORE TRUNCATE ON login_tokens
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER login_tokens_integer_numbers BEFORE INSERT OR UPDATE ON login_tokens
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
