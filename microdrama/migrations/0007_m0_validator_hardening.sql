-- 0007 M0 validator hardening (findings V-1, V-2, V-3, V-6, V-8, V-9, V-10, V-11).
-- Appended rather than editing applied migrations.

-- V-1: approvals are judged against the server clock; callers cannot backdate them.
CREATE OR REPLACE FUNCTION md_approval_requires_human_session() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  s record;
BEGIN
  NEW.created_at := clock_timestamp();  -- audit time is server time, never caller-supplied
  SELECT hs.owner_id, hs.expires_at, hs.revoked_at, o.active
    INTO s
    FROM human_sessions hs JOIN owners o ON o.id = hs.owner_id
   WHERE hs.id = NEW.actor_session_id;
  IF NOT FOUND OR s.owner_id <> NEW.actor_owner_id OR NOT s.active
     OR s.revoked_at IS NOT NULL OR s.expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'approval events require a live human owner session'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;

-- Sorted text array of a jsonb array of strings (for order-insensitive hash-set equality).
CREATE FUNCTION md_sorted_text_array(j jsonb) RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM jsonb_array_elements_text(j) AS x
$$;

-- V-2: a season can only be approved by a real Gate 1 APPROVE bound to its scope hash.
ALTER TABLE seasons
  ADD CONSTRAINT seasons_approval_event_fk FOREIGN KEY (approval_event_id) REFERENCES approval_events(id);

CREATE FUNCTION md_season_approval_binding() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.approval_event_id IS NOT NULL
     AND (NEW.approval_event_id IS DISTINCT FROM OLD.approval_event_id
          OR NEW.approved_scope_hash IS DISTINCT FROM OLD.approved_scope_hash
          OR NEW.approved_scope_version IS DISTINCT FROM OLD.approved_scope_version) THEN
    RAISE EXCEPTION 'a season approval cannot be rebound' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.approval_event_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM approval_events a
        WHERE a.id = NEW.approval_event_id
          AND a.gate_type = 'SEASON_CONCEPT' AND a.action = 'APPROVE'
          AND a.entity_id = NEW.id AND a.package_hash = NEW.approved_scope_hash) THEN
    RAISE EXCEPTION 'season approval must reference a Gate 1 APPROVE for this season and scope hash'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER seasons_approval_binding BEFORE INSERT OR UPDATE ON seasons
  FOR EACH ROW EXECUTE FUNCTION md_season_approval_binding();

-- V-3: package status machine; APPROVED/REVISED/REJECTED bind a matching Gate 2 decision.
CREATE FUNCTION md_release_package_binding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  a record;
  allowed text[];
  expected_action text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF OLD.approval_event_id IS NOT NULL AND NEW.approval_event_id IS DISTINCT FROM OLD.approval_event_id THEN
      RAISE EXCEPTION 'a package decision cannot be rebound' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status THEN
      allowed := CASE OLD.status
        WHEN 'DRAFT'    THEN ARRAY['READY','BLOCKED','SUPERSEDED']
        WHEN 'READY'    THEN ARRAY['BLOCKED','APPROVED','REVISED','REJECTED','SUPERSEDED']
        WHEN 'BLOCKED'  THEN ARRAY['READY','REVISED','REJECTED','SUPERSEDED']
        WHEN 'APPROVED' THEN ARRAY['SUPERSEDED']
        ELSE ARRAY[]::text[]
      END;
      IF NOT (NEW.status = ANY (allowed)) THEN
        RAISE EXCEPTION 'release package % -> % is not allowed', OLD.status, NEW.status
          USING ERRCODE = 'check_violation';
      END IF;
    END IF;
  ELSIF NEW.status NOT IN ('DRAFT','READY','BLOCKED') THEN
    RAISE EXCEPTION 'new release packages start as DRAFT, READY or BLOCKED' USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.status IN ('APPROVED','REVISED','REJECTED')
     AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status) THEN
    expected_action := CASE NEW.status WHEN 'APPROVED' THEN 'APPROVE'
                                       WHEN 'REVISED' THEN 'REVISE' ELSE 'REJECT' END;
    SELECT * INTO a FROM approval_events WHERE id = NEW.approval_event_id;
    IF NOT FOUND OR a.gate_type <> 'EPISODE_FINAL' OR a.entity_id <> NEW.episode_id
       OR a.package_hash <> NEW.package_hash OR a.action <> expected_action THEN
      RAISE EXCEPTION 'package decision must reference the matching Gate 2 event for this package'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.status = 'APPROVED' AND (
         md_sorted_text_array(a.media_hashes) <> md_sorted_text_array(NEW.media_hashes)
         OR a.management_policy_hash IS DISTINCT FROM NEW.management_policy_hash
         OR a.release_scope_hash IS DISTINCT FROM NEW.release_scope_hash
         OR jsonb_array_length(NEW.gate_blockers) <> 0) THEN
      RAISE EXCEPTION 'approval must bind this package''s media, policy and release scope with no blockers'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER release_packages_binding BEFORE INSERT OR UPDATE ON release_packages
  FOR EACH ROW EXECUTE FUNCTION md_release_package_binding();

-- An episode reaches release states only with an APPROVED package (set that package first).
CREATE FUNCTION md_episode_release_requires_approval() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.state IN ('RELEASE_APPROVED','SCHEDULED','PUBLISHING','PUBLISHED_VERIFIED','MANAGED')
     AND (TG_OP = 'INSERT' OR OLD.state IS DISTINCT FROM NEW.state)
     AND NOT EXISTS (SELECT 1 FROM release_packages p WHERE p.episode_id = NEW.id AND p.status = 'APPROVED') THEN
    RAISE EXCEPTION 'episode % cannot enter % without an APPROVED release package', NEW.id, NEW.state
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER episodes_release_requires_approval BEFORE INSERT OR UPDATE ON episodes
  FOR EACH ROW EXECUTE FUNCTION md_episode_release_requires_approval();

-- V-6: management qualification can never be recorded without ten windows.
ALTER TABLE qualification_runs
  ADD CONSTRAINT qualification_runs_management_ten CHECK (management_status <> 'QUALIFIED' OR consecutive >= 10);

-- V-8: append-only tables also refuse TRUNCATE (statement level).
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['domain_events','manual_interventions','canon_versions','approval_events',
                           'feedback_events','identity_locks','identity_lock_assets','budget_transfers','charges',
                           'cost_allocations','cost_overruns','pod_usage_intervals','asset_lineage',
                           'hook_experiments','qa_observations','metadata_versions','performance_snapshots',
                           'qualification_runs','policy_versions'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation()',
                   t || '_no_truncate', t);
  END LOOP;
END $$;

-- V-9: the stored descriptor is as immutable as the columns it duplicates.
DROP TRIGGER assets_content_immutable ON assets;
CREATE TRIGGER assets_content_immutable BEFORE UPDATE ON assets
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns('asset_kind', 'object_key', 'sha256', 'size_bytes', 'media_type',
                                                     'media', 'provenance', 'generation_key', 'descriptor');
ALTER TABLE assets
  ADD CONSTRAINT assets_descriptor_matches CHECK (
    descriptor->>'sha256' = sha256 AND descriptor->>'object_key' = object_key AND descriptor->>'asset_id' = id::text);

-- V-10: a publication slot's media hash must be the asset's actual hash.
ALTER TABLE assets ADD CONSTRAINT assets_id_sha256_key UNIQUE (id, sha256);
ALTER TABLE platform_posts
  ADD CONSTRAINT platform_posts_asset_hash_fk FOREIGN KEY (asset_id, asset_sha256) REFERENCES assets(id, sha256);

-- V-11: metered management actions cannot be EXECUTED without a reservation.
-- The body is the contracts.ManagementAction JSON, which always states its estimate;
-- a missing estimate is not treated as zero.
ALTER TABLE management_actions
  ADD CONSTRAINT management_actions_body_states_cost CHECK (body ? 'estimated_cost_micro_usd'),
  ADD CONSTRAINT management_actions_metered_needs_reservation CHECK (
    decision <> 'EXECUTED' OR reservation_id IS NOT NULL
    OR (body->>'estimated_cost_micro_usd')::bigint = 0);

-- V-7 (DB side): an enabled preset row must carry its measurement.
ALTER TABLE preset_registry
  ADD CONSTRAINT preset_registry_enabled_measured CHECK (
    NOT enabled OR (record ? 'measured' AND jsonb_typeof(record->'measured') = 'object'));
