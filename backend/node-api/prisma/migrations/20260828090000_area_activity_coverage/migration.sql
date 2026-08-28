ALTER TABLE "area_activity_collection_state"
    ADD COLUMN "source_kind" VARCHAR(20) NOT NULL DEFAULT 'UNAVAILABLE',
    ADD COLUMN "source_fingerprint" VARCHAR(64),
    ADD COLUMN "source_ref" VARCHAR(1000),
    ADD COLUMN "source_duration_seconds" REAL,
    ADD COLUMN "covered_intervals" JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN "coverage_percent" REAL NOT NULL DEFAULT 0,
    ADD COLUMN "coverage_status" VARCHAR(20) NOT NULL DEFAULT 'NOT_STARTED',
    ADD COLUMN "completed_at" TIMESTAMPTZ;

ALTER TABLE "area_activity_collection_state"
    ADD CONSTRAINT "chk_area_activity_coverage_kind"
        CHECK ("source_kind" IN ('LOCAL_FILE', 'LIVE', 'UNAVAILABLE')),
    ADD CONSTRAINT "chk_area_activity_coverage_status"
        CHECK ("coverage_status" IN ('NOT_STARTED', 'PARTIAL', 'COMPLETE', 'STALE', 'UNAVAILABLE')),
    ADD CONSTRAINT "chk_area_activity_coverage_percent"
        CHECK ("coverage_percent" >= 0 AND "coverage_percent" <= 100),
    ADD CONSTRAINT "chk_area_activity_coverage_intervals"
        CHECK (jsonb_typeof("covered_intervals") = 'array');

CREATE INDEX "idx_area_activity_source_ref_entered"
    ON "area_activity_sessions"("source_ref", "entered_at" DESC);
