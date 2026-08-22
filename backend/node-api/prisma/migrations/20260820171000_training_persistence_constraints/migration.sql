-- Legacy rows may not have provenance. New trainable rows must carry a valid source contract.
ALTER TABLE "label_samples"
  ADD CONSTRAINT "chk_label_samples_media_kind"
    CHECK ("media_kind" IS NULL OR "media_kind" IN ('IMAGE', 'VIDEO')),
  ADD CONSTRAINT "chk_label_samples_frame_timestamp"
    CHECK (
      ("media_kind" IS NULL AND "frame_timestamp_ms" IS NULL)
      OR ("media_kind" = 'VIDEO' AND "frame_timestamp_ms" >= 0)
      OR ("media_kind" = 'IMAGE' AND "frame_timestamp_ms" IS NULL)
    );

ALTER TABLE "model_versions"
  ADD CONSTRAINT "chk_model_versions_evaluated"
    CHECK ("status" NOT IN ('ACTIVE', 'REJECTED') OR "evaluated_at" IS NOT NULL),
  ADD CONSTRAINT "chk_model_versions_activated"
    CHECK ("status" <> 'ACTIVE' OR "activated_at" IS NOT NULL),
  ADD CONSTRAINT "chk_model_versions_artifact_hash"
    CHECK ("artifact_sha256" ~ '^[0-9a-f]{64}$');
