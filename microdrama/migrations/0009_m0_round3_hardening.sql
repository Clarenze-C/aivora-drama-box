-- 0009 M0 round-3 hardening (N-5, N-6, N-7, N-8, N-9, N-10). Closes whole classes:
-- deletion of audit records, the caption/approval seam, and floats anywhere in stored rows.

-- Caption conditions shared by the Gate 2 APPROVE record and the APPROVED transition:
-- at least one listed track; every listed track CURRENT + actual-audio aligned for this
-- episode; no CURRENT non-aligned track for the episode.
CREATE FUNCTION md_package_captions_releasable(p_episode uuid, p_body jsonb) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT jsonb_typeof(p_body->'caption_track_ids') = 'array'
     AND jsonb_array_length(p_body->'caption_track_ids') >= 1
     AND NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements_text(p_body->'caption_track_ids') AS t(id)
            WHERE NOT EXISTS (SELECT 1 FROM caption_tracks c
                               WHERE c.id::text = t.id AND c.episode_id = p_episode
                                 AND c.state = 'CURRENT' AND c.timing_source = 'ACTUAL_AUDIO_ALIGNMENT'))
     AND NOT EXISTS (SELECT 1 FROM caption_tracks c
                      WHERE c.episode_id = p_episode AND c.state = 'CURRENT'
                        AND c.timing_source <> 'ACTUAL_AUDIO_ALIGNMENT')
$$;

-- N-8: decision-time check uses the shared rule (replaces the 0008 caption checks).
CREATE OR REPLACE FUNCTION md_gate2_decision_requires_package() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  p record;
BEGIN
  IF NEW.gate_type <> 'EPISODE_FINAL' THEN
    RETURN NEW;
  END IF;
  SELECT * INTO p FROM release_packages
   WHERE episode_id = NEW.entity_id AND package_hash = NEW.package_hash;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Gate 2 decision references no release package of this episode'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.action = 'APPROVE' THEN
    IF p.status <> 'READY' OR jsonb_array_length(p.gate_blockers) <> 0 THEN
      RAISE EXCEPTION 'Gate 2 approval requires a READY package with no blockers (package is %)', p.status
        USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT md_package_captions_releasable(NEW.entity_id, p.body) THEN
      RAISE EXCEPTION 'Gate 2 approval refused: caption tracks must exist, be CURRENT and be aligned to actual audio'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  ELSIF p.status NOT IN ('READY','BLOCKED') THEN
    RAISE EXCEPTION 'Gate 2 % requires a READY or BLOCKED package (package is %)', NEW.action, p.status
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

-- N-7: the APPROVED transition re-checks the caption rule (separate trigger, runs after
-- the 0007 binding trigger because trigger names sort after it).
CREATE FUNCTION md_release_package_captions_at_approval() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'APPROVED' AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status)
     AND NOT md_package_captions_releasable(NEW.episode_id, NEW.body) THEN
    RAISE EXCEPTION 'package cannot become APPROVED: caption tracks must be CURRENT and aligned to actual audio'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER release_packages_zz_captions_at_approval BEFORE INSERT OR UPDATE ON release_packages
  FOR EACH ROW EXECUTE FUNCTION md_release_package_captions_at_approval();

-- N-6 (and the whole deletion class): records the audit trail depends on are never deleted;
-- lifecycle happens through states (SUPERSEDED/INVALIDATED/CANCELLED ...).
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['seasons','season_proposals','episodes','scripts','shot_manifests','characters',
                           'voices','reference_versions','preference_rules','assets','edit_manifests',
                           'caption_tracks','repair_plans','qa_findings','release_packages','platform_posts',
                           'community_events','management_actions','membership_catalog','entitlement_links',
                           'jobs','provider_operations','reservations','budget_accounts',
                           'budget_category_allocations','pod_leases','idempotency_records','webhook_events',
                           'capability_registry','rights_registry','preset_registry','credential_refs'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE DELETE ON %I FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation()',
                   t || '_no_delete', t);
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation()',
                   t || '_no_truncate', t);
  END LOOP;
END $$;

-- N-9 (and the whole float class): no stored row may contain a non-integer number anywhere,
-- including inside jsonb documents however they were bound (Python object or JSON text).
-- policy_versions.body keeps the original policy file verbatim (it contains USD decimals)
-- and is exempt; it is settings input, never money state.
CREATE FUNCTION md_jsonb_has_non_integer(j jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
  SELECT EXISTS (SELECT 1 FROM jsonb_path_query(j, 'strict $.** ? (@.type() == "number")') AS n(v)
                  WHERE n.v::text ~ '[.eE]')
$$;

CREATE FUNCTION md_forbid_non_integer_numbers() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF md_jsonb_has_non_integer(to_jsonb(NEW)) THEN
    RAISE EXCEPTION '% rows cannot contain non-integer numbers (money is integer micro-USD, time is integer ms)',
      TG_TABLE_NAME USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

DO $$
DECLARE
  t text;
BEGIN
  FOR t IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND c.relname NOT IN ('policy_versions','schema_migrations','md_runtime_mode') LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers()',
                   t || '_integer_numbers', t);
  END LOOP;
END $$;

-- N-10: a registry row counts as live-evidenced only if at least one entry names a real,
-- non-fake evidence source from the closed set; anything else is treated as fake-only.
CREATE OR REPLACE FUNCTION md_evidence_fake_only(evidence jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
  SELECT NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements(coalesce(evidence, '[]'::jsonb)) AS e(item)
     WHERE (CASE jsonb_typeof(e.item) WHEN 'string' THEN e.item #>> '{}' ELSE e.item->>'source' END)
           IN ('OFFICIAL_DOCUMENTATION','CONTROLLED_ACCOUNT_TEST','MEASURED_BENCHMARK','LICENSE_DOCUMENT'))
$$;

-- N-5: NULL-safe enabled-preset backstop (a missing key fails instead of passing as NULL).
ALTER TABLE preset_registry DROP CONSTRAINT preset_registry_enabled_measured;
ALTER TABLE preset_registry
  ADD CONSTRAINT preset_registry_enabled_measured CHECK (
    NOT enabled OR (
      jsonb_typeof(record->'measured') = 'object'
      AND coalesce((record->'measured'->>'critical_quality_pass_bp')::bigint, 0) > 0
      AND coalesce((record->'measured'->>'sample_count')::bigint, 0) > 0
      AND (record->'measured') ? 'cost_per_accepted_shot_micro_usd'));
