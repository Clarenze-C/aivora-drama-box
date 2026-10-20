-- 0008 M0 re-validation hardening (findings N-3, V-22, V-4, N-5). Appended, never edited.

-- N-3 + V-22: a Gate 2 decision can only be recorded against a current package in a
-- decidable state. APPROVE needs a READY package with no blockers whose caption tracks are
-- all CURRENT and aligned to actual audio; REVISE/REJECT need a READY or BLOCKED package.
CREATE FUNCTION md_gate2_decision_requires_package() RETURNS trigger LANGUAGE plpgsql AS $$
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
    IF EXISTS (SELECT 1 FROM caption_tracks c
                WHERE c.episode_id = NEW.entity_id AND c.state = 'CURRENT'
                  AND c.timing_source <> 'ACTUAL_AUDIO_ALIGNMENT') THEN
      RAISE EXCEPTION 'Gate 2 approval refused: a current caption track is not aligned to actual audio'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(p.body->'caption_track_ids', '[]'::jsonb)) AS t(id)
                WHERE NOT EXISTS (SELECT 1 FROM caption_tracks c
                                   WHERE c.id::text = t.id AND c.episode_id = NEW.entity_id
                                     AND c.state = 'CURRENT' AND c.timing_source = 'ACTUAL_AUDIO_ALIGNMENT')) THEN
      RAISE EXCEPTION 'Gate 2 approval refused: package caption tracks must be CURRENT and aligned to actual audio'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  ELSIF p.status NOT IN ('READY','BLOCKED') THEN
    RAISE EXCEPTION 'Gate 2 % requires a READY or BLOCKED package (package is %)', NEW.action, p.status
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER approval_events_gate2_package BEFORE INSERT ON approval_events
  FOR EACH ROW EXECUTE FUNCTION md_gate2_decision_requires_package();

-- V-22: a caption recut invalidates the approval. A caption track used by an APPROVED package
-- cannot leave CURRENT until that package is SUPERSEDED (which returns it to Gate 2).
CREATE FUNCTION md_caption_change_requires_reapproval() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state = 'CURRENT' AND NEW.state <> 'CURRENT' AND EXISTS (
       SELECT 1 FROM release_packages p
        WHERE p.episode_id = OLD.episode_id AND p.status = 'APPROVED'
          AND coalesce(p.body->'caption_track_ids', '[]'::jsonb) ? OLD.id::text) THEN
    RAISE EXCEPTION 'caption track % is part of an approved package; supersede the package first', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER caption_tracks_reapproval BEFORE UPDATE ON caption_tracks
  FOR EACH ROW EXECUTE FUNCTION md_caption_change_requires_reapproval();

-- V-4: this database's execution mode. A database in any live mode cannot hold enabled or
-- ELIGIBLE registry records whose evidence is only FAKE_FIXTURE, and cannot be switched to a
-- live mode while such records are enabled. Test/mock databases stay OFFLINE_MOCK.
CREATE TABLE md_runtime_mode (
  singleton       boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  execution_mode  text NOT NULL CHECK (execution_mode IN ('OFFLINE_MOCK','PAID_BENCHMARK',
                                                          'CONTROLLED_ACCOUNT_TEST','PRODUCTION')),
  changed_at      timestamptz NOT NULL DEFAULT now()
);
INSERT INTO md_runtime_mode (execution_mode) VALUES ('OFFLINE_MOCK');

-- True when every evidence item (a string or an object with "source") is FAKE_FIXTURE.
CREATE FUNCTION md_evidence_fake_only(evidence jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_array_length(evidence) > 0 AND NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements(evidence) AS e(item)
     WHERE coalesce(CASE jsonb_typeof(e.item) WHEN 'string' THEN e.item #>> '{}'
                                               ELSE e.item->>'source' END, '') <> 'FAKE_FIXTURE')
$$;

CREATE FUNCTION md_registry_fake_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  mode text;
  active boolean;
  evidence jsonb;
BEGIN
  SELECT execution_mode INTO mode FROM md_runtime_mode;
  IF mode = 'OFFLINE_MOCK' THEN
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME = 'rights_registry' THEN
    active := NEW.status = 'ELIGIBLE';
    evidence := NEW.evidence;
  ELSIF TG_TABLE_NAME = 'capability_registry' THEN
    active := NEW.enabled;
    evidence := NEW.evidence_sources;
  ELSE
    active := NEW.enabled;
    evidence := NEW.evidence;
  END IF;
  IF active AND md_evidence_fake_only(evidence) THEN
    RAISE EXCEPTION '% rows backed only by FAKE_FIXTURE evidence cannot be active in %', TG_TABLE_NAME, mode
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rights_registry_fake_guard BEFORE INSERT OR UPDATE ON rights_registry
  FOR EACH ROW EXECUTE FUNCTION md_registry_fake_evidence_guard();
CREATE TRIGGER capability_registry_fake_guard BEFORE INSERT OR UPDATE ON capability_registry
  FOR EACH ROW EXECUTE FUNCTION md_registry_fake_evidence_guard();
CREATE TRIGGER preset_registry_fake_guard BEFORE INSERT OR UPDATE ON preset_registry
  FOR EACH ROW EXECUTE FUNCTION md_registry_fake_evidence_guard();

CREATE FUNCTION md_runtime_mode_change_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'the runtime mode row cannot be deleted' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.execution_mode <> 'OFFLINE_MOCK' AND (
       EXISTS (SELECT 1 FROM rights_registry WHERE current AND status = 'ELIGIBLE' AND md_evidence_fake_only(evidence))
    OR EXISTS (SELECT 1 FROM capability_registry WHERE current AND enabled AND md_evidence_fake_only(evidence_sources))
    OR EXISTS (SELECT 1 FROM preset_registry WHERE current AND enabled AND md_evidence_fake_only(evidence))) THEN
    RAISE EXCEPTION 'cannot leave OFFLINE_MOCK while fake-evidence registry rows are active'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  NEW.changed_at := clock_timestamp();
  RETURN NEW;
END $$;
CREATE TRIGGER md_runtime_mode_guard BEFORE UPDATE OR DELETE ON md_runtime_mode
  FOR EACH ROW EXECUTE FUNCTION md_runtime_mode_change_guard();
CREATE TRIGGER md_runtime_mode_no_truncate BEFORE TRUNCATE ON md_runtime_mode
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();

-- N-5: the enabled-preset backstop matches the contract (non-zero quality, cost present).
ALTER TABLE preset_registry DROP CONSTRAINT preset_registry_enabled_measured;
ALTER TABLE preset_registry
  ADD CONSTRAINT preset_registry_enabled_measured CHECK (
    NOT enabled OR (
      jsonb_typeof(record->'measured') = 'object'
      AND (record->'measured'->>'critical_quality_pass_bp')::bigint > 0
      AND (record->'measured'->>'cost_per_accepted_shot_micro_usd') IS NOT NULL
      AND (record->'measured'->>'sample_count')::bigint > 0));
