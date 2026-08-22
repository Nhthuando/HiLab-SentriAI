ALTER TABLE "label_samples"
  ADD COLUMN "media_ref" VARCHAR(500),
  ADD COLUMN "media_kind" VARCHAR(10),
  ADD COLUMN "frame_timestamp_ms" INTEGER;

CREATE TABLE "training_datasets" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(),
  "manifest_path" VARCHAR(500) NOT NULL,
  "content_hash" VARCHAR(64) NOT NULL,
  "sample_count" INTEGER NOT NULL,
  "source_count" INTEGER NOT NULL,
  "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "training_datasets_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "uq_training_datasets_content_hash" UNIQUE ("content_hash"),
  CONSTRAINT "chk_training_datasets_counts" CHECK ("sample_count" > 0 AND "source_count" > 0)
);

CREATE TABLE "training_jobs" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(), "dataset_id" UUID NOT NULL,
  "status" VARCHAR(20) NOT NULL DEFAULT 'QUEUED', "base_model" VARCHAR(100) NOT NULL,
  "current_epoch" INTEGER NOT NULL DEFAULT 0, "total_epochs" INTEGER NOT NULL,
  "pause_reason" VARCHAR(50), "failure_reason" TEXT,
  "requested_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, "started_at" TIMESTAMPTZ, "completed_at" TIMESTAMPTZ,
  CONSTRAINT "training_jobs_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "fk_training_jobs_dataset_id" FOREIGN KEY ("dataset_id") REFERENCES "training_datasets"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT "chk_training_jobs_status" CHECK ("status" IN ('QUEUED','RUNNING','PAUSED_GPU','EVALUATING','SUCCEEDED','FAILED')),
  CONSTRAINT "chk_training_jobs_epochs" CHECK ("current_epoch" >= 0 AND "total_epochs" > 0 AND "current_epoch" <= "total_epochs")
);
CREATE INDEX "idx_training_jobs_requested_at_desc" ON "training_jobs" ("requested_at" DESC);
CREATE INDEX "idx_training_jobs_status_requested_at" ON "training_jobs" ("status", "requested_at" DESC);

CREATE TABLE "model_versions" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(), "training_job_id" UUID NOT NULL,
  "version_key" VARCHAR(100) NOT NULL, "base_model" VARCHAR(100) NOT NULL,
  "artifact_path" VARCHAR(500) NOT NULL, "artifact_sha256" VARCHAR(64) NOT NULL,
  "status" VARCHAR(20) NOT NULL DEFAULT 'CANDIDATE', "evaluation_metrics" JSONB,
  "evaluated_at" TIMESTAMPTZ, "activated_at" TIMESTAMPTZ, "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "model_versions_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "uq_model_versions_training_job_id" UNIQUE ("training_job_id"),
  CONSTRAINT "uq_model_versions_version_key" UNIQUE ("version_key"),
  CONSTRAINT "fk_model_versions_training_job_id" FOREIGN KEY ("training_job_id") REFERENCES "training_jobs"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT "chk_model_versions_status" CHECK ("status" IN ('CANDIDATE','ACTIVE','INACTIVE','REJECTED'))
);
CREATE UNIQUE INDEX "uq_model_versions_one_active" ON "model_versions" (("status")) WHERE "status" = 'ACTIVE';
CREATE INDEX "idx_model_versions_created_at_desc" ON "model_versions" ("created_at" DESC);
