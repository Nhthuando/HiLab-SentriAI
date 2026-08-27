# BAI-KIEM Overlapping Box Arbitration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicate overlays during generic-to-custom promotion and suppress the measured reach-stacker component false positive without hiding grounded people.

**Architecture:** Frontend presentation reconciliation recognizes only the safe generic-vehicle to confirmed reach-stacker semantic upgrade. Backend output arbitration adds a narrow person-inside-confirmed-reach predicate based on containment, area, confidence, and bottom gap. Neither path adds inference or modifies V8.

**Tech Stack:** React 19, TypeScript 6, Python 3.12, NumPy, unittest, Ultralytics YOLO11.

## Global Constraints

- Do not train or modify model/dataset artifacts.
- Keep custom thresholds 0.40 initiation and 0.25 continuation.
- Keep two-of-three confirmation and custom inference interval 2.
- Add no inference pass.
- Preserve real people at the vehicle/ground boundary.
- Leave changes uncommitted and run `git diff --check`.

---

### Task 1: Frontend semantic-upgrade reconciliation

**Files:**
- Modify: `frontend/src/hooks/useAreaMonitor.ts`

**Interfaces:**
- Produces: `isAuthoritativeVehicleSemanticUpgrade(previousClass, currentClass) -> boolean`.
- Consumes: existing zone-sharing and box-continuity predicates.

- [ ] Export a pure predicate that returns true only for `truck|car|bus -> reach_stacker`.
- [ ] Allow presentation-entry reuse when classes match or that predicate passes.
- [ ] Preserve current actual-ID and presentation-ID bookkeeping.
- [ ] Run `npm.cmd run lint` and `npm.cmd run build` in `frontend`.

### Task 2: Backend contained-person arbitration

**Files:**
- Modify: `backend/python-worker/detection/tracked_detector.py`
- Modify: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- Produces: `_is_person_component_false_positive(detection, active_records) -> bool`.
- Consumes: confirmed custom records and pixel bounding boxes.

- [ ] Add a failing test with a confidence-0.44 person fully contained in the upper reach box; assert only reach remains.
- [ ] Add preservation tests for a grounded person, a confidence-0.70 person, and a person outside the reach box.
- [ ] Implement the narrow five-condition predicate from the design.
- [ ] Apply it in confirmed-custom output arbitration after generic-vehicle suppression.
- [ ] Run focused Area tests.

### Task 3: Regression and live verification

**Files:**
- Verify: `backend/python-worker/tests/`
- Verify: `frontend/src/`
- Inspect: `backend/data/runtime-logs/`

**Interfaces:**
- Consumes production `/ws/feed/area` and playback seek endpoints.

- [ ] Run all Python unittests and Node API typecheck.
- [ ] Run frontend lint and production build.
- [ ] Restart only the Python worker and confirm one V8 load, no inference failures, no reconnect loop, and no deprecated `half` warning.
- [ ] Probe 04:24 for generic-to-reach transitions and 04:39 for contained person overlaps.
- [ ] Run `git diff --check` and decide whether the remaining evidence justifies V9 training.
