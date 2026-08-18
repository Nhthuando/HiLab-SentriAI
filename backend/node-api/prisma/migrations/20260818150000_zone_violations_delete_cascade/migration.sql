-- Test-zone cleanup: deleting a zone also deletes its linked violations.
ALTER TABLE "zone_violations"
  DROP CONSTRAINT "zone_violations_zone_id_fkey",
  ADD CONSTRAINT "zone_violations_zone_id_fkey"
    FOREIGN KEY ("zone_id") REFERENCES "zones"("id")
    ON DELETE CASCADE
    ON UPDATE CASCADE;
