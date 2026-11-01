-- T039: add the frozen 2.3.0 SeasonStoryLedger to the V2 document allowlist.
-- Keep the complete 0019 allowlist so existing document types and rows remain valid.
ALTER TABLE v2_contract_documents
  DROP CONSTRAINT v2_contract_documents_contract_type_check;

ALTER TABLE v2_contract_documents
  ADD CONSTRAINT v2_contract_documents_contract_type_check CHECK (contract_type IN (
    'ConceptIntake', 'ConceptCandidate', 'CharacterLogic', 'SecretLedger',
    'EpisodePack', 'StoryTime', 'WardrobeBible', 'SceneWardrobeAssignment',
    'StateEvent', 'AssetSheet', 'PropSheet', 'StyleBible', 'LocationLayout', 'ShotReferenceBinding',
    'PromptManifest', 'ProgressSnapshot', 'ReleaseApprovalManifest', 'SeasonStoryLedger'
  ));
