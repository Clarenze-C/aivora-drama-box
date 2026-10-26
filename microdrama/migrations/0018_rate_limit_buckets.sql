-- 0018 shared rate-limit buckets (build-review F04).
-- One row per provider+account key: the bucket shape (capacity/refill, set by the
-- integrator's configuration) plus the token state every worker process shares.
-- Acquire takes the row lock, so separate worker processes and restarts see ONE
-- allowance per account — a process-local dictionary could not enforce that.
-- House guards: no delete/truncate, integer columns stay integral.

CREATE TABLE rate_limit_buckets (
  limiter_key        text PRIMARY KEY CHECK (length(limiter_key) BETWEEN 3 AND 200),
  capacity           integer NOT NULL CHECK (capacity >= 1),
  refill_per_second  integer NOT NULL CHECK (refill_per_second >= 1),
  milli_tokens       bigint NOT NULL CHECK (milli_tokens >= 0),
  last_ms            bigint NOT NULL CHECK (last_ms >= 0),
  revision           integer NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
CREATE TRIGGER rate_limit_buckets_no_delete BEFORE DELETE ON rate_limit_buckets
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER rate_limit_buckets_no_truncate BEFORE TRUNCATE ON rate_limit_buckets
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER rate_limit_buckets_integer_numbers BEFORE INSERT OR UPDATE ON rate_limit_buckets
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
