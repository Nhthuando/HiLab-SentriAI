ALTER TABLE "zone_violations"
ADD COLUMN "source_kind" VARCHAR(20),
ADD COLUMN "source_ref" VARCHAR(1000),
ADD COLUMN "source_position_seconds" DOUBLE PRECISION,
ADD COLUMN "source_timestamp" TIMESTAMPTZ,
ADD COLUMN "clip_status" VARCHAR(20) NOT NULL DEFAULT 'NOT_REQUESTED',
ADD COLUMN "clip_requested_at" TIMESTAMPTZ,
ADD COLUMN "clip_error" TEXT;

UPDATE "zone_violations"
SET "clip_status" = CASE
  WHEN "clip_path" IS NOT NULL THEN 'READY'
  ELSE 'NOT_REQUESTED'
END;

ALTER TABLE "zone_violations"
ADD CONSTRAINT "chk_zone_violations_clip_status"
CHECK ("clip_status" IN ('NOT_REQUESTED','QUEUED','GENERATING','READY','FAILED','EXPIRED'));
