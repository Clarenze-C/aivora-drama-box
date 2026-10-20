-- 0011 M0 round-5 hardening (R5-2, R5-3, R5-4). Minor tightenings.

-- R5-2: a hook exposure's identity cannot change while its platform_post_id is filled.
-- (platform_post_id is a reference to platform_posts filled at publication.)
DROP TRIGGER hook_exposures_ledger_immutable ON hook_exposures;
CREATE TRIGGER hook_exposures_ledger_immutable BEFORE UPDATE ON hook_exposures
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('id', 'experiment_id', 'candidate_id', 'platform',
                                                     'account_ref', 'release_slot', 'cohort', 'scheduled_utc',
                                                     'duration_ms', 'subtitle_locale', 'offer_ref', 'traffic',
                                                     'created_at');
ALTER TABLE hook_exposures
  ADD CONSTRAINT hook_exposures_platform_post_fk FOREIGN KEY (platform_post_id) REFERENCES platform_posts(id);

-- R5-3: a sequence counter's aggregate identity is fixed.
CREATE TRIGGER aggregate_sequences_identity_immutable BEFORE UPDATE ON aggregate_sequences
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('aggregate_id', 'aggregate_type');

-- R5-4: enabled-preset measurements are within contract ranges (micro-USD >= 0; bp 1..10000).
ALTER TABLE preset_registry DROP CONSTRAINT preset_registry_enabled_measured;
ALTER TABLE preset_registry
  ADD CONSTRAINT preset_registry_enabled_measured CHECK (
    NOT enabled OR coalesce(
      jsonb_typeof(record->'measured') = 'object'
      AND jsonb_typeof(record->'measured'->'critical_quality_pass_bp') = 'number'
      AND jsonb_typeof(record->'measured'->'sample_count') = 'number'
      AND jsonb_typeof(record->'measured'->'cost_per_accepted_shot_micro_usd') = 'number'
      AND (record->'measured'->>'critical_quality_pass_bp')::bigint BETWEEN 1 AND 10000
      AND (record->'measured'->>'sample_count')::bigint > 0
      AND (record->'measured'->>'cost_per_accepted_shot_micro_usd')::bigint >= 0,
      false));
