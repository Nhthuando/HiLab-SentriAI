-- Add CHECK constraints for all tables
-- These constraints enforce valid state values as specified in docs/database/database.md §5
-- Prisma does not emit CHECK constraints natively; added as a separate raw SQL migration.

-- registered_vehicles: status must be KNOWN or STRANGER
ALTER TABLE "registered_vehicles"
  ADD CONSTRAINT "chk_registered_vehicles_status"
  CHECK (status IN ('KNOWN', 'STRANGER'));

-- gate_events: lane, status, and confidence range constraints
ALTER TABLE "gate_events"
  ADD CONSTRAINT "chk_gate_events_lane"
  CHECK (lane IN ('IN_1', 'IN_2'));

ALTER TABLE "gate_events"
  ADD CONSTRAINT "chk_gate_events_status"
  CHECK (status IN ('KNOWN', 'STRANGER'));

ALTER TABLE "gate_events"
  ADD CONSTRAINT "chk_gate_events_confidence"
  CHECK (confidence >= 0.0 AND confidence <= 1.0);

-- zones: rule_type must be one of the two defined rule modes
ALTER TABLE "zones"
  ADD CONSTRAINT "chk_zones_rule_type"
  CHECK (rule_type IN ('PROHIBIT_SPECIFIED', 'ALLOW_SPECIFIED'));

-- zone_violations: status and duration_seconds constraints
ALTER TABLE "zone_violations"
  ADD CONSTRAINT "chk_zone_violations_status"
  CHECK (status IN ('OPEN', 'CLOSED'));

ALTER TABLE "zone_violations"
  ADD CONSTRAINT "chk_zone_violations_duration"
  CHECK (duration_seconds IS NULL OR duration_seconds >= 0);

-- chat_messages: role must be user or assistant
ALTER TABLE "chat_messages"
  ADD CONSTRAINT "chk_chat_messages_role"
  CHECK (role IN ('user', 'assistant'));
