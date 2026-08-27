# BAI-KIEM Overlapping Box Arbitration Design

## Problem

Two visually similar defects have different causes in `KiemHoa-Hik (2).mp4`.

At approximately 04:24, the server emits a COCO `truck` on one frame and a confirmed custom `reach_stacker` on the next. It emits zero same-frame overlaps, but the frontend retains the missing truck presentation for 900 ms and refuses to re-associate it because the canonical class changed. The browser therefore draws both boxes temporarily.

At approximately 04:39, the server really emits both detections. The confirmed reach stacker has confidence 0.595-0.627, while COCO mistakes a machine component for `person` at confidence 0.170-0.444. The person box is completely contained by the reach box and ends well above the machine's ground contact.

## Goals

- Draw one presentation box during a spatially continuous generic-vehicle to reach-stacker promotion.
- Suppress the measured machine-component `person` false positive without hiding a person standing beside or in front of the vehicle.
- Keep the current V8 artifact, custom 0.40/0.25 thresholds, two-of-three confirmation, inference interval, and inference count unchanged.
- Preserve stable presentation IDs, zone/event semantics, and real-person detections.

## Frontend arbitration

The Area presentation cache may reuse an existing spatially continuous entry when the prior class is `truck`, `car`, or `bus` and the current class is `reach_stacker`. This is an authoritative semantic upgrade, not ordinary cross-class re-identification. The entry immediately adopts the custom class, box, label, status, and actual track ID while retaining its presentation ID. Ordinary unrelated cross-class detections remain separate.

## Backend person/reach arbitration

A COCO `person` is treated as a reach-stacker component false positive only when all conditions hold:

- A confirmed active `reach_stacker` record exists.
- At least 90% of the person box is contained by the reach box.
- Person area is at most 35% of reach area.
- Person confidence is below 0.50.
- The person's bottom edge is at least 12% of reach height above the reach bottom edge.

The bottom-gap condition preserves a real person whose feet align with the vehicle/ground region. The rule is applied only to already-confirmed reach stackers; it never changes model output before confirmation and never affects person detections outside that envelope.

## Verification and training decision

- Unit tests cover frontend semantic-upgrade eligibility and backend suppression/preservation geometry.
- Python tests, Node typecheck, frontend lint/build, and formatting checks pass.
- Live WebSocket probes at 04:24 and 04:39 show no overlapping generic vehicle or floating contained person box after reach confirmation.
- The runtime fix adds no inference pass. Retraining is recommended only if raw V8 still misses/relabels the reach stacker after runtime arbitration, or if false detections survive with geometry/confidence outside the narrow safety rule.

## Non-goals

- No V9 training or dataset mutation.
- No global cross-class NMS.
- No blanket suppression of people overlapping vehicles.
- No claim of universal accuracy across unseen cameras.
