-- 0010 M0 round-4 hardening (N-11, N-12, N-13, N-14, N-15). Every table is now in the
-- deletion class; a catalog test (tests/integration/persistence/test_schema_catalog.py)
-- fails if any present or future table lacks the guards.

-- N-11: the caption helper is total (never NULL), so callers cannot pass on NULL.
CREATE OR REPLACE FUNCTION md_package_captions_releasable(p_episode uuid, p_body jsonb) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT coalesce(
       jsonb_typeof(p_body->'caption_track_ids') = 'array'
       AND jsonb_array_length(p_body->'caption_track_ids') >= 1
       AND NOT EXISTS (
             SELECT 1 FROM jsonb_array_elements_text(p_body->'caption_track_ids') AS t(id)
              WHERE NOT EXISTS (SELECT 1 FROM caption_tracks c
                                 WHERE c.id::text = t.id AND c.episode_id = p_episode
                                   AND c.state = 'CURRENT' AND c.timing_source = 'ACTUAL_AUDIO_ALIGNMENT'))
       AND NOT EXISTS (SELECT 1 FROM caption_tracks c
                        WHERE c.episode_id = p_episode AND c.state = 'CURRENT'
                          AND c.timing_source <> 'ACTUAL_AUDIO_ALIGNMENT'),
       false)
$$;

-- N-12 / N-13 / N-14: the remaining tables join the deletion class.
-- Consumer dedupe, dispatch records and the hook exposure ledger are append-only; a hook
-- exposure may only gain its platform_post_id once it is published.
CREATE TRIGGER event_consumptions_append_only BEFORE UPDATE OR DELETE ON event_consumptions
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER event_dispatches_append_only BEFORE UPDATE OR DELETE ON event_dispatches
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

CREATE FUNCTION md_hook_exposure_publish_once() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.platform_post_id IS NOT NULL OR NEW.platform_post_id IS NULL THEN
    RAISE EXCEPTION 'hook exposures are append-only; only an unset platform_post_id may be filled'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER hook_exposures_publish_once BEFORE UPDATE ON hook_exposures
  FOR EACH ROW EXECUTE FUNCTION md_hook_exposure_publish_once();
CREATE TRIGGER hook_exposures_ledger_immutable BEFORE UPDATE ON hook_exposures
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('experiment_id', 'candidate_id', 'platform', 'account_ref',
                                                     'release_slot', 'cohort', 'scheduled_utc', 'duration_ms',
                                                     'subtitle_locale', 'offer_ref', 'traffic');

-- Sequence counters never move backwards (a reset would re-issue event sequences).
CREATE FUNCTION md_sequence_monotonic() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.last_sequence < OLD.last_sequence OR NEW.aggregate_id <> OLD.aggregate_id THEN
    RAISE EXCEPTION 'aggregate sequences are monotonic' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER aggregate_sequences_monotonic BEFORE UPDATE ON aggregate_sequences
  FOR EACH ROW EXECUTE FUNCTION md_sequence_monotonic();

-- Migration history is append-only too (the runner only inserts).
CREATE TRIGGER schema_migrations_append_only BEFORE UPDATE OR DELETE ON schema_migrations
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['event_consumptions','event_dispatches','hook_exposures','aggregate_sequences',
                           'owners','human_sessions','service_credentials','schema_migrations'] LOOP
    IF t NOT IN ('event_consumptions','event_dispatches','schema_migrations') THEN
      EXECUTE format('CREATE TRIGGER %I BEFORE DELETE ON %I FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation()',
                     t || '_no_delete', t);
    END IF;
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation()',
                   t || '_no_truncate', t);
  END LOOP;
END $$;

-- N-15: enabled-preset measurements must be JSON numbers (not null, not strings).
ALTER TABLE preset_registry DROP CONSTRAINT preset_registry_enabled_measured;
ALTER TABLE preset_registry
  ADD CONSTRAINT preset_registry_enabled_measured CHECK (
    NOT enabled OR coalesce(
      jsonb_typeof(record->'measured') = 'object'
      AND jsonb_typeof(record->'measured'->'critical_quality_pass_bp') = 'number'
      AND jsonb_typeof(record->'measured'->'sample_count') = 'number'
      AND jsonb_typeof(record->'measured'->'cost_per_accepted_shot_micro_usd') = 'number'
      AND (record->'measured'->>'critical_quality_pass_bp')::bigint > 0
      AND (record->'measured'->>'sample_count')::bigint > 0,
      false));
