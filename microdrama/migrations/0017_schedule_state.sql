-- 0017 schedule firing state (T029 in-app scheduling).
-- Only prevents busy-spinning between timer invocations: effect dedupe stays with
-- the jobs table's semantic keys, so lost rows can never double-fire an effect.
-- House guards: no delete/truncate, integer columns stay integral.

CREATE TABLE schedule_state (
  schedule_id   text PRIMARY KEY CHECK (schedule_id ~ '^[a-z0-9][a-z0-9._\-]{1,80}$'),
  last_fired_at timestamptz NOT NULL,
  fired_count   integer NOT NULL DEFAULT 1 CHECK (fired_count >= 1)
);
CREATE TRIGGER schedule_state_identity_immutable BEFORE UPDATE ON schedule_state
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('schedule_id');
CREATE TRIGGER schedule_state_no_delete BEFORE DELETE ON schedule_state
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER schedule_state_no_truncate BEFORE TRUNCATE ON schedule_state
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER schedule_state_integer_numbers BEFORE INSERT OR UPDATE ON schedule_state
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
