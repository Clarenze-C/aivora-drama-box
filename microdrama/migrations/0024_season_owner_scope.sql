-- T044a: explicit season-to-owner relation. Every review/workbench read (season,
-- proposal, episode, media, progress) scopes to it. Legacy seasons without a uniquely
-- verified human Gate 1 approval stay unassigned and hidden until an audited
-- operator assignment; new intake links its creator at creation
-- (review.scope.link_season_creator).
--
-- The durable progress projection this enables reads the current DirectingManifest
-- of an episode as its required-work denominator; that core payload (V2 2.0,
-- compiled by story.directing) was never allowlisted for persistence. Extend the
-- 0019/0020 allowlist with it so the denominator can be stored at all.

ALTER TABLE v2_contract_documents
  DROP CONSTRAINT v2_contract_documents_contract_type_check;

ALTER TABLE v2_contract_documents
  ADD CONSTRAINT v2_contract_documents_contract_type_check CHECK (contract_type IN (
    'ConceptIntake', 'ConceptCandidate', 'CharacterLogic', 'SecretLedger',
    'EpisodePack', 'StoryTime', 'WardrobeBible', 'SceneWardrobeAssignment',
    'StateEvent', 'AssetSheet', 'PropSheet', 'StyleBible', 'LocationLayout', 'ShotReferenceBinding',
    'PromptManifest', 'ProgressSnapshot', 'ReleaseApprovalManifest', 'SeasonStoryLedger',
    'DirectingManifest'
  ));

CREATE TABLE season_owners (
  season_id          uuid PRIMARY KEY REFERENCES seasons(id),
  owner_id           uuid NOT NULL REFERENCES owners(id),
  source             text NOT NULL CHECK (source IN ('GATE1_APPROVAL_BACKFILL','CREATOR_AT_CREATION','AUDITED_ASSIGNMENT')),
  approval_event_id  uuid REFERENCES approval_events(id),
  assigned_at        timestamptz NOT NULL DEFAULT now(),
  CHECK ((source = 'GATE1_APPROVAL_BACKFILL') = (approval_event_id IS NOT NULL))
);
CREATE INDEX season_owners_owner_idx ON season_owners (owner_id);

-- One owner per season, and a backfill row must cite the season's own human
-- Gate 1 APPROVE whose actor is that owner (approval_events itself guarantees a
-- live human session actor). Only GATE1_APPROVAL_BACKFILL provenance is
-- DATABASE-enforced. CREATOR_AT_CREATION/AUDITED_ASSIGNMENT rows carry no
-- approval event; today they are guarded by the application layer alone
-- (review.scope.link_season_creator refuses every non-human principal), because
-- all services share one DB role that the trigger cannot distinguish. DB-role
-- isolation and an audited assignment control are T046 work; there is
-- deliberately no assignment endpoint yet.
CREATE FUNCTION md_season_owner_provenance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  ae record;
BEGIN
  IF NEW.approval_event_id IS NOT NULL THEN
    SELECT * INTO ae FROM approval_events WHERE id = NEW.approval_event_id;
    IF NOT FOUND OR ae.gate_type <> 'SEASON_CONCEPT' OR ae.action <> 'APPROVE'
       OR ae.entity_type <> 'season' OR ae.entity_id <> NEW.season_id
       OR ae.actor_owner_id <> NEW.owner_id THEN
      RAISE EXCEPTION 'season owner link must cite the season''s own human Gate 1 approval'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER season_owners_provenance BEFORE INSERT ON season_owners
  FOR EACH ROW EXECUTE FUNCTION md_season_owner_provenance();

-- Ownership history is audit provenance: append-only like the approvals it cites.
CREATE TRIGGER season_owners_append_only BEFORE UPDATE OR DELETE ON season_owners
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER season_owners_no_truncate BEFORE TRUNCATE ON season_owners
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER season_owners_integer_numbers BEFORE INSERT OR UPDATE ON season_owners
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

-- Backfill: only seasons whose own row names a Gate 1 APPROVE (V-2 guarantees the
-- binding) that is the season's UNIQUE human approval event. Seasons with zero or
-- several candidate approvals (ambiguous legacy provenance) stay unassigned.
INSERT INTO season_owners (season_id, owner_id, source, approval_event_id)
SELECT s.id, a.actor_owner_id, 'GATE1_APPROVAL_BACKFILL', a.id
FROM seasons s
JOIN approval_events a ON a.id = s.approval_event_id
WHERE a.gate_type = 'SEASON_CONCEPT' AND a.action = 'APPROVE'
  AND a.entity_type = 'season' AND a.entity_id = s.id
  AND (SELECT count(*) FROM approval_events x
        WHERE x.gate_type = 'SEASON_CONCEPT' AND x.action = 'APPROVE'
          AND x.entity_type = 'season' AND x.entity_id = s.id) = 1;
