-- T038: append-only persistence for V2 canonical payload revisions.
-- Payload validation/hash calculation remains in the typed Python contract layer.

CREATE TABLE v2_contract_documents (
  contract_type       text NOT NULL CHECK (contract_type IN (
    'ConceptIntake', 'ConceptCandidate', 'CharacterLogic', 'SecretLedger',
    'EpisodePack', 'StoryTime', 'WardrobeBible', 'SceneWardrobeAssignment',
    'StateEvent', 'AssetSheet', 'PropSheet', 'StyleBible', 'LocationLayout', 'ShotReferenceBinding',
    'PromptManifest', 'ProgressSnapshot', 'ReleaseApprovalManifest'
  )),
  record_id           uuid NOT NULL,
  version             integer NOT NULL CHECK (version >= 1),
  payload             jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'
                                             AND payload->>'schema_version' = '2.0'),
  payload_sha256      text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  rights_route_id     text CHECK (rights_route_id ~ '^[a-z0-9][a-z0-9_.\-]{0,119}$'),
  rights_version      integer CHECK (rights_version >= 1),
  valid_from          timestamptz NOT NULL,
  valid_until         timestamptz,
  current             boolean NOT NULL DEFAULT true,
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (contract_type, record_id, version),
  CHECK (valid_until IS NULL OR valid_until > valid_from),
  CHECK ((rights_route_id IS NULL) = (rights_version IS NULL))
);
CREATE UNIQUE INDEX v2_contract_documents_current
  ON v2_contract_documents (contract_type, record_id) WHERE current;
CREATE TRIGGER v2_contract_documents_immutable BEFORE UPDATE ON v2_contract_documents
  FOR EACH ROW EXECUTE FUNCTION md_immutable_columns(
    'contract_type', 'record_id', 'version', 'payload', 'payload_sha256',
    'rights_route_id', 'rights_version', 'valid_from', 'valid_until', 'created_at'
  );
CREATE TRIGGER v2_contract_documents_no_delete BEFORE DELETE ON v2_contract_documents
  FOR EACH ROW EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER v2_contract_documents_no_truncate BEFORE TRUNCATE ON v2_contract_documents
  FOR EACH STATEMENT EXECUTE FUNCTION md_forbid_mutation();
CREATE TRIGGER v2_contract_documents_integer_numbers BEFORE INSERT OR UPDATE ON v2_contract_documents
  FOR EACH ROW EXECUTE FUNCTION md_forbid_non_integer_numbers();
