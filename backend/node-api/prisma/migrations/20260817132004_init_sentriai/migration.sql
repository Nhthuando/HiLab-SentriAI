-- CreateTable
CREATE TABLE "registered_vehicles" (
    "id" UUID NOT NULL,
    "plate_number" VARCHAR(20) NOT NULL,
    "status" VARCHAR(20) NOT NULL DEFAULT 'KNOWN',
    "note" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "registered_vehicles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "gate_events" (
    "id" UUID NOT NULL,
    "camera_id" VARCHAR(50) NOT NULL,
    "lane" VARCHAR(20) NOT NULL,
    "license_plate" VARCHAR(20) NOT NULL,
    "status" VARCHAR(20) NOT NULL,
    "confidence" REAL NOT NULL,
    "crop_path" VARCHAR(500),
    "clip_path" VARCHAR(500),
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "gate_events_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "zones" (
    "id" UUID NOT NULL,
    "camera_id" VARCHAR(50) NOT NULL,
    "name" VARCHAR(100) NOT NULL,
    "polygon_points" JSONB NOT NULL,
    "rule_type" VARCHAR(50) NOT NULL DEFAULT 'PROHIBIT_SPECIFIED',
    "target_labels" JSONB NOT NULL DEFAULT '[]',
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "zones_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "zone_violations" (
    "id" UUID NOT NULL,
    "camera_id" VARCHAR(50) NOT NULL,
    "zone_id" UUID NOT NULL,
    "object_label" VARCHAR(100) NOT NULL,
    "status" VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    "entered_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "exited_at" TIMESTAMPTZ,
    "duration_seconds" INTEGER,
    "clip_path" VARCHAR(500),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "zone_violations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "object_labels" (
    "id" UUID NOT NULL,
    "vietnamese_name" VARCHAR(100) NOT NULL,
    "base_class" VARCHAR(50) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "object_labels_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "label_samples" (
    "id" UUID NOT NULL,
    "label_id" UUID NOT NULL,
    "image_path" VARCHAR(500) NOT NULL,
    "bbox" JSONB NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "label_samples_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "chat_messages" (
    "id" UUID NOT NULL,
    "role" VARCHAR(20) NOT NULL,
    "content" TEXT NOT NULL,
    "clip_reference" VARCHAR(500),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "chat_messages_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "registered_vehicles_plate_number_key" ON "registered_vehicles"("plate_number");

-- CreateIndex
CREATE INDEX "idx_gate_events_timestamp_desc" ON "gate_events"("timestamp" DESC);

-- CreateIndex
CREATE INDEX "idx_gate_events_license_plate" ON "gate_events"("license_plate");

-- CreateIndex
CREATE INDEX "idx_gate_events_status_timestamp" ON "gate_events"("status", "timestamp" DESC);

-- CreateIndex
CREATE INDEX "idx_zones_camera_active" ON "zones"("camera_id", "is_active");

-- CreateIndex
CREATE UNIQUE INDEX "zones_camera_id_name_key" ON "zones"("camera_id", "name");

-- CreateIndex
CREATE INDEX "idx_zone_violations_entered_at_desc" ON "zone_violations"("entered_at" DESC);

-- CreateIndex
CREATE INDEX "idx_zone_violations_zone_entered" ON "zone_violations"("zone_id", "entered_at" DESC);

-- CreateIndex
CREATE INDEX "idx_zone_violations_active_tracking" ON "zone_violations"("zone_id", "status");

-- CreateIndex
CREATE UNIQUE INDEX "object_labels_vietnamese_name_key" ON "object_labels"("vietnamese_name");

-- CreateIndex
CREATE INDEX "idx_label_samples_label_id" ON "label_samples"("label_id");

-- CreateIndex
CREATE INDEX "idx_chat_messages_created_at_asc" ON "chat_messages"("created_at" ASC);

-- AddForeignKey
ALTER TABLE "zone_violations" ADD CONSTRAINT "zone_violations_zone_id_fkey" FOREIGN KEY ("zone_id") REFERENCES "zones"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "label_samples" ADD CONSTRAINT "label_samples_label_id_fkey" FOREIGN KEY ("label_id") REFERENCES "object_labels"("id") ON DELETE CASCADE ON UPDATE CASCADE;
