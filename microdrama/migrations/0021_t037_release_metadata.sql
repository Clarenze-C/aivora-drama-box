-- T037: bind a V2 release manifest to the same immutable human Gate 2 event.
-- Legacy V1 approvals keep package_hash and leave release_manifest_hash NULL.
ALTER TABLE approval_events
  ADD COLUMN release_manifest_hash text
    CHECK (release_manifest_hash IS NULL OR release_manifest_hash ~ '^[0-9a-f]{64}$');

CREATE TABLE approved_slot_metadata (
  metadata_id uuid NOT NULL,
  metadata_version integer NOT NULL CHECK (metadata_version >= 1),
  release_package_id uuid NOT NULL REFERENCES release_packages(id),
  release_package_hash text NOT NULL CHECK (release_package_hash ~ '^[0-9a-f]{64}$'),
  slot_id text NOT NULL,
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  is_current boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (metadata_id, metadata_version),
  UNIQUE (release_package_id, slot_id, metadata_id, metadata_version)
);
CREATE TABLE release_approval_manifests (
  manifest_hash text PRIMARY KEY CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
  manifest_id uuid NOT NULL,
  version integer NOT NULL CHECK (version >= 1),
  release_package_id uuid NOT NULL REFERENCES release_packages(id),
  release_package_hash text NOT NULL CHECK (release_package_hash ~ '^[0-9a-f]{64}$'),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  created_at timestamptz NOT NULL,
  UNIQUE (manifest_id, version)
);
CREATE TRIGGER release_approval_manifests_immutable BEFORE UPDATE OR DELETE ON release_approval_manifests
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER release_approval_manifests_no_truncate BEFORE TRUNCATE ON release_approval_manifests
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER release_approval_manifests_integer_numbers BEFORE INSERT OR UPDATE ON release_approval_manifests
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
CREATE UNIQUE INDEX approved_slot_metadata_one_current
  ON approved_slot_metadata (release_package_id, slot_id) WHERE is_current;
CREATE TRIGGER approved_slot_metadata_immutable BEFORE UPDATE ON approved_slot_metadata
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns(
    'metadata_id', 'metadata_version', 'release_package_id', 'release_package_hash',
    'slot_id', 'content_sha256', 'payload', 'created_at'
  );
CREATE TRIGGER approved_slot_metadata_no_delete BEFORE DELETE ON approved_slot_metadata
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER approved_slot_metadata_no_truncate BEFORE TRUNCATE ON approved_slot_metadata
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER approved_slot_metadata_integer_numbers BEFORE INSERT OR UPDATE ON approved_slot_metadata
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();

CREATE FUNCTION md_gate2_manifest_binding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p record; m record;
BEGIN
  IF NEW.gate_type <> 'EPISODE_FINAL' OR NEW.action <> 'APPROVE' THEN
    IF NEW.release_manifest_hash IS NOT NULL THEN
      RAISE EXCEPTION 'only Gate 2 APPROVE can bind a release manifest'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.release_manifest_hash IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO p FROM release_packages
   WHERE episode_id = NEW.entity_id AND package_hash = NEW.package_hash;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Gate 2 manifest must bind the package named by package_hash'
      USING ERRCODE = 'foreign_key_violation';
  END IF;
  SELECT * INTO m FROM release_approval_manifests
   WHERE manifest_hash = NEW.release_manifest_hash
     AND payload->>'approval_manifest_sha256' = manifest_hash
     AND payload->>'release_package_id' = p.id::text
     AND payload->>'release_package_hash' = p.package_hash;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Gate 2 manifest is missing or belongs to another package'
      USING ERRCODE = 'foreign_key_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER approval_events_gate2_manifest BEFORE INSERT ON approval_events
  FOR EACH ROW EXECUTE FUNCTION md_gate2_manifest_binding();

CREATE FUNCTION md_approved_slot_metadata_binding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p record;
BEGIN
  SELECT id, package_hash INTO p FROM release_packages WHERE id = NEW.release_package_id;
  IF NOT FOUND OR p.package_hash <> NEW.release_package_hash THEN
    RAISE EXCEPTION 'approved slot metadata package binding is stale'
      USING ERRCODE = 'foreign_key_violation';
  END IF;
  IF NEW.payload->>'metadata_id' <> NEW.metadata_id::text
     OR (NEW.payload->>'metadata_version')::integer <> NEW.metadata_version
     OR NEW.payload->>'slot_id' <> NEW.slot_id
     OR NEW.payload->>'content_sha256' <> NEW.content_sha256 THEN
    RAISE EXCEPTION 'approved slot metadata payload does not match indexed identity'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER approved_slot_metadata_binding BEFORE INSERT ON approved_slot_metadata
  FOR EACH ROW EXECUTE FUNCTION md_approved_slot_metadata_binding();

