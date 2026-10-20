-- 0012 M1 integrator (T005 review): a closed reservation records why it closed, so release
-- and expiry reasons stay in the audit trail. Active reservations carry no reason; every
-- SETTLED / RELEASED / EXPIRED reservation carries one (1..500 characters, one line).
ALTER TABLE reservations ADD COLUMN closed_reason text;
ALTER TABLE reservations
  ADD CONSTRAINT reservations_closed_reason_matches_state CHECK (
    (state = 'ACTIVE') = (closed_reason IS NULL)
    AND (closed_reason IS NULL
         OR (length(closed_reason) BETWEEN 1 AND 500 AND closed_reason !~ '[\r\n]')));

-- A RELEASED reservation is terminal: its reason never changes afterwards.
CREATE FUNCTION md_reservation_release_reason_final() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state = 'RELEASED' AND (NEW.state <> 'RELEASED' OR NEW.closed_reason IS DISTINCT FROM OLD.closed_reason) THEN
    RAISE EXCEPTION 'a released reservation keeps its state and reason' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reservations_release_reason_final BEFORE UPDATE ON reservations
  FOR EACH ROW EXECUTE FUNCTION md_reservation_release_reason_final();
