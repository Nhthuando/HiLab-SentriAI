CREATE TABLE "area_activity_sessions" (
    "id" UUID NOT NULL,
    "camera_id" VARCHAR(50) NOT NULL,
    "zone_id" UUID,
    "zone_name" VARCHAR(100) NOT NULL,
    "object_label" VARCHAR(100) NOT NULL,
    "canonical_class" VARCHAR(100) NOT NULL,
    "policy_result" VARCHAR(20) NOT NULL,
    "session_status" VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    "entered_at" TIMESTAMPTZ NOT NULL,
    "last_seen_at" TIMESTAMPTZ NOT NULL,
    "exited_at" TIMESTAMPTZ,
    "duration_seconds" INTEGER,
    "track_id" INTEGER,
    "entry_point" JSONB NOT NULL,
    "source_kind" VARCHAR(20) NOT NULL,
    "source_ref" VARCHAR(1000),
    "source_position_seconds" REAL,
    "source_timestamp" TIMESTAMPTZ,
    "event_fingerprint" VARCHAR(64),
    "violation_id" UUID,
    "clip_path" VARCHAR(500),
    "clip_status" VARCHAR(20) NOT NULL DEFAULT 'NOT_REQUESTED',
    "clip_requested_at" TIMESTAMPTZ,
    "clip_error" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "area_activity_sessions_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "chk_area_activity_policy" CHECK ("policy_result" IN ('ALLOWED', 'VIOLATION')),
    CONSTRAINT "chk_area_activity_status" CHECK ("session_status" IN ('OPEN', 'CLOSED')),
    CONSTRAINT "chk_area_activity_lifecycle" CHECK (
      ("session_status" = 'OPEN' AND "exited_at" IS NULL AND "duration_seconds" IS NULL)
      OR
      ("session_status" = 'CLOSED' AND "exited_at" IS NOT NULL AND "duration_seconds" >= 0)
    ),
    CONSTRAINT "chk_area_activity_source" CHECK ("source_kind" IN ('LOCAL_FILE', 'LIVE', 'UNAVAILABLE')),
    CONSTRAINT "chk_area_activity_clip_status" CHECK ("clip_status" IN ('NOT_REQUESTED', 'QUEUED', 'GENERATING', 'READY', 'FAILED', 'EXPIRED')),
    CONSTRAINT "area_activity_sessions_zone_id_fkey" FOREIGN KEY ("zone_id") REFERENCES "zones"("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "uq_area_activity_fingerprint" ON "area_activity_sessions"("event_fingerprint") WHERE "event_fingerprint" IS NOT NULL;
CREATE UNIQUE INDEX "area_activity_sessions_violation_id_key" ON "area_activity_sessions"("violation_id");
CREATE INDEX "idx_area_activity_entered_desc" ON "area_activity_sessions"("entered_at" DESC);
CREATE INDEX "idx_area_activity_class_entered" ON "area_activity_sessions"("canonical_class", "entered_at" DESC);
CREATE INDEX "idx_area_activity_zone_entered" ON "area_activity_sessions"("zone_id", "entered_at" DESC);
CREATE INDEX "idx_area_activity_policy_entered" ON "area_activity_sessions"("policy_result", "entered_at" DESC);
CREATE INDEX "idx_area_activity_open_last_seen" ON "area_activity_sessions"("session_status", "last_seen_at" DESC);

CREATE TABLE "area_activity_collection_state" (
    "camera_id" VARCHAR(50) NOT NULL,
    "started_at" TIMESTAMPTZ NOT NULL,
    "last_observed_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "area_activity_collection_state_pkey" PRIMARY KEY ("camera_id")
);

INSERT INTO "area_activity_sessions" (
    "id", "camera_id", "zone_id", "zone_name", "object_label", "canonical_class",
    "policy_result", "session_status", "entered_at", "last_seen_at", "exited_at",
    "duration_seconds", "track_id", "entry_point", "source_kind", "source_ref",
    "source_position_seconds", "source_timestamp", "event_fingerprint", "violation_id",
    "clip_path", "clip_status", "clip_requested_at", "clip_error", "created_at", "updated_at"
)
SELECT
    gen_random_uuid(), violation.camera_id, violation.zone_id, zone.name,
    violation.object_label, COALESCE(label.base_class, LOWER(REPLACE(violation.object_label, ' ', '_'))),
    'VIOLATION', violation.status, violation.entered_at,
    COALESCE(violation.exited_at, violation.entered_at), violation.exited_at,
    violation.duration_seconds, NULL, '{"x":0,"y":0}'::jsonb,
    COALESCE(violation.source_kind, 'UNAVAILABLE'), violation.source_ref,
    violation.source_position_seconds, violation.source_timestamp, NULL, violation.id,
    violation.clip_path, violation.clip_status, violation.clip_requested_at, violation.clip_error,
    violation.created_at, CURRENT_TIMESTAMP
FROM "zone_violations" violation
JOIN "zones" zone ON zone.id = violation.zone_id
LEFT JOIN "object_labels" label ON LOWER(label.vietnamese_name) = LOWER(violation.object_label)
ON CONFLICT ("violation_id") DO NOTHING;
