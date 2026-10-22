-- 0016 T020 release core: publishing provider operations are free platform API calls, so they
-- join UNMETERED_OPERATION_KINDS at the contract level (1.6.0) and this migration relaxes
-- migration 0013's linkage CHECK for exactly those kinds, as its header prescribed. Job linkage
-- stays mandatory: recovery still finds in-flight publish operations through their job, and the
-- application guard (core.provider_ops.begin) still refuses any unlisted kind without a
-- reservation before SQL runs. Only the four publish kinds may omit reservation_id.
ALTER TABLE provider_operations DROP CONSTRAINT provider_operations_linked;
ALTER TABLE provider_operations
  ADD CONSTRAINT provider_operations_linked CHECK (
    job_id IS NOT NULL
    AND (
      reservation_id IS NOT NULL
      OR operation_kind IN ('publish.submit_slot', 'publish.poll_status',
                            'publish.reconcile_slot', 'publish.update_metadata')
    )
  );
