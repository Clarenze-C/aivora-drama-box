-- 0013 M1 round-2 (V-14, V-24): every provider operation is linked to its job and to the budget
-- reservation that pays for it, so recovery and budget release always see it. Contract 1.4.0 has
-- no unmetered operation kinds; adding one requires a new migration that relaxes this check for
-- exactly that kind.
ALTER TABLE provider_operations
  ADD CONSTRAINT provider_operations_linked CHECK (job_id IS NOT NULL AND reservation_id IS NOT NULL);
