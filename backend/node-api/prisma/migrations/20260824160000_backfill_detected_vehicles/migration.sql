INSERT INTO "registered_vehicles" (
  "id",
  "plate_number",
  "status",
  "note",
  "created_at",
  "updated_at"
)
SELECT
  gen_random_uuid(),
  detected."plate_number",
  'STRANGER',
  'Tự động thêm từ lịch sử nhận diện GATE-01',
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
FROM (
  SELECT DISTINCT UPPER(TRIM("license_plate")) AS "plate_number"
  FROM "gate_events"
  WHERE TRIM("license_plate") <> ''
) AS detected
ON CONFLICT ("plate_number") DO NOTHING;
