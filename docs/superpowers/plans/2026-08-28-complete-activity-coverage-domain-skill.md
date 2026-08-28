# Complete Activity Coverage and Domain Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make BAI-KIEM activity statistics cover the complete local source independently of UI viewers, disclose incomplete coverage, and load a project-owned SentriAI domain `SKILL.md` into Gemini.

**Architecture:** Keep one Area inference pipeline. Separate analytics activation from viewer/frame emission, accumulate source-time coverage in a pure tracker, persist coverage snapshots additively, and make QA totals coverage-aware. Store the canonical domain policy in a standard `SKILL.md`; load and validate it at Node startup instead of duplicating policy in TypeScript.

**Tech Stack:** Python 3/FastAPI/OpenCV/asyncpg, PostgreSQL/Neon, Prisma/TypeScript/Express, Gemini function calling, React/Vite.

**Execution note:** Implement inline in the current worktree because the user explicitly requested automatic execution and the required `executing-plans` skill is unavailable. Do not create commits because `.git` is read-only in this workspace session.

---

## File map

- Create `backend/python-worker/zone/coverage_tracker.py`: pure merge/status logic for local and live coverage.
- Modify `backend/python-worker/detection/area_pipeline.py`: analytics/viewer state separation and coverage snapshot scheduling.
- Modify `backend/python-worker/main.py`: activation endpoint controls viewer state only for Area.
- Modify `backend/python-worker/db/repositories.py` and `db/__init__.py`: persist structured coverage and clear it with Area history.
- Create migration `backend/node-api/prisma/migrations/20260828090000_area_activity_coverage/migration.sql` and modify Prisma schema.
- Create `backend/node-api/src/ai/domain/sentriai-operations/SKILL.md`: canonical runtime domain policy.
- Create `backend/node-api/src/ai/domainSkill.ts`: deterministic path resolution, frontmatter validation, and content loading.
- Modify `backend/node-api/src/ai/prompts.ts`, `gemini.ts`, `tools.ts`: load skill and enforce coverage-aware answer context.
- Modify `backend/node-api/src/services/clipService.ts`, frontend types, and `AIQAChat.tsx`: persist/render structured coverage with activity evidence.
- Create focused Python/Node tests and a real-video ground-truth manifest.

### Task 1: Pure coverage tracker

**Files:**
- Create: `backend/python-worker/zone/coverage_tracker.py`
- Create: `backend/python-worker/tests/test_activity_coverage_tracker.py`

**Interfaces:**
- Produce `CoverageSnapshot` with `source_kind`, `source_fingerprint`, `source_duration_seconds`, `covered_intervals`, `coverage_percent`, `coverage_status`, and `completed_at`.
- Produce `ActivityCoverageTracker.observe(position_seconds, duration_seconds, observed_at)` and `snapshot()`.

- [ ] Write tests for unordered/overlapping interval merge, seek gaps, near-complete threshold, source change reset, and live observed intervals.
- [ ] Run `pytest tests/test_activity_coverage_tracker.py -q`; expect failures because the module is absent.
- [ ] Implement finite-value validation, half-open interval merging with one inference-step tolerance, and the 99% plus beginning/end completion rule.
- [ ] Run the focused test and existing tracker tests; expect all pass.

### Task 2: Additive persistence contract

**Files:**
- Modify: `backend/node-api/prisma/schema.prisma`
- Create: `backend/node-api/prisma/migrations/20260828090000_area_activity_coverage/migration.sql`
- Modify: `backend/python-worker/db/repositories.py`
- Modify: `backend/python-worker/db/__init__.py`
- Modify: `backend/python-worker/tests/test_area_activity_repository.py`

**Interfaces:**
- Replace heartbeat-only writes with `update_area_activity_collection(camera_id, snapshot, observed_at)`.
- Preserve `touch_area_activity_collection` as a compatibility wrapper for live/legacy tests.

- [ ] Write repository SQL-shape tests for JSON interval persistence, status validation, source change replacement, and coverage deletion with Area reset.
- [ ] Extend Prisma state with nullable/additive source/coverage fields and enum-like SQL checks.
- [ ] Implement one upsert that updates only non-regressing snapshots for the same fingerprint and resets the ledger for a changed fingerprint.
- [ ] Validate Prisma and run repository tests.

### Task 3: Decouple analytics from viewers

**Files:**
- Modify: `backend/python-worker/detection/area_pipeline.py`
- Modify: `backend/python-worker/main.py`
- Modify: `backend/python-worker/tests/test_area_pipeline.py`

**Interfaces:**
- `AreaPipeline.set_viewer_active(active: bool)` controls frame emission demand.
- `AreaPipeline.pause()` no longer serves subscriber disconnects for BAI-KIEM; analytics stops only during shutdown/reset or explicit maintenance.
- `publish_result(result, emit_frame=...)` always queues transitions/coverage but conditionally emits rendered frames.

- [ ] Add tests proving `viewer_active=false` still processes/persists activity and coverage while skipping `emit_frame`.
- [ ] Add seek/reset tests proving coverage gaps are not marked complete and open sessions close safely.
- [ ] Implement viewer state and coverage observation from frozen source metadata.
- [ ] Change the activation endpoint to call `set_viewer_active` for Area and retain existing Gate activation behavior.
- [ ] Run the full Area/tracker Python suites.

### Task 4: Create and validate the domain skill

**Files:**
- Create: `backend/node-api/src/ai/domain/sentriai-operations/SKILL.md`
- Create: `backend/node-api/src/ai/domainSkill.ts`
- Create: `backend/node-api/src/tests/test_domain_skill.ts`
- Modify: `backend/node-api/src/ai/prompts.ts`

**Interfaces:**
- Export `loadSentriAiDomainSkill(): string`.
- Export `QA_SYSTEM_PROMPT` as the safety preamble plus the exact loaded skill text.

- [ ] Initialize the skill folder with the official `skill-creator` script, without unused assets/references.
- [ ] Replace generated placeholders with taxonomy, counting, coverage, timezone, evidence, privacy, and answer-template rules.
- [ ] Write tests for required frontmatter, required policy headings, missing-file failure, and prompt inclusion.
- [ ] Implement deterministic source/dist path resolution without exposing the path in API errors.
- [ ] Run `quick_validate.py` and Node domain-skill tests.

### Task 5: Coverage-aware QA tools and deterministic answers

**Files:**
- Modify: `backend/node-api/src/ai/tools.ts`
- Modify: `backend/node-api/src/ai/gemini.ts`
- Modify: `backend/node-api/src/tests/test_qa_chat.ts`

**Interfaces:**
- Activity tool results include `coverage.status`, `coverage.percent`, `coverage.sourceDurationSeconds`, `coverage.coveredIntervals`, `coverage.lastObservedAtLocal`, and `coverage.complete`.
- Deterministic activity routing injects a mandatory answer policy alongside verified tool output.

- [ ] Add tests where one truck row plus 20% coverage cannot produce a complete-total instruction.
- [ ] Add tests where complete coverage can produce a complete-source total.
- [ ] Filter local rows to the current source reference when the collection state has one.
- [ ] Mark old heartbeat-only state as `PARTIAL`, never `COMPLETE`.
- [ ] Run QA tests, typecheck, and build.

### Task 6: Persist and render structured coverage

**Files:**
- Modify: `backend/node-api/src/services/clipService.ts`
- Modify: `backend/node-api/src/routes/qa.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/components/AIQAChat.tsx`
- Modify relevant API mapping tests.

**Interfaces:**
- Add optional `coverage` to `ActivityEvidence` so chat reference hydration can reconstruct current coverage.
- Render `Đã xử lý toàn bộ video` or `Dữ liệu tạm tính · đã xử lý X% video` below activity evidence.

- [ ] Write type/serialization tests for additive coverage.
- [ ] Enrich activity evidence from collection state without changing clip request status.
- [ ] Render complete/partial/stale labels accessibly and keep existing `Xem video` behavior unchanged.
- [ ] Run frontend lint/build and Node tests.

### Task 7: Real-video oracle and regression acceptance

**Files:**
- Create: `docs/evaluation/bai-kiem-truck-ground-truth.json`
- Update: approved spec/task/handoff documents with actual evidence only.

**Interfaces:**
- Manifest entries contain `source`, `canonicalClass`, `zoneName`, `entryRangeSeconds`, and `exitRangeSeconds`.

- [ ] Review the complete source at sampled candidate windows and annotate every visible truck zone-entry.
- [ ] Reset only BAI-KIEM activity/coverage test rows after exact-target confirmation.
- [ ] Run the complete source until coverage is `COMPLETE`; compare persisted truck sessions to the manifest.
- [ ] Run a second complete loop; assert row count and existing timestamps/durations/`updatedAt` are unchanged.
- [ ] Assert every activity clip remains `NOT_REQUESTED`, then click/request exactly one evidence clip and verify 202/poll/206.
- [ ] Ask Gemini the truck question and assert its count equals direct aggregation and wording declares complete coverage.
- [ ] Run Python suites, Node QA/clip tests, Prisma validation, typecheck/build, frontend lint/build, Team1 validators, and `git diff --check`.

## Plan self-review

- Spec coverage: every acceptance criterion maps to Tasks 1–7.
- Placeholders: none; the real count is intentionally derived from the reviewed manifest rather than hard-coded from visual estimation.
- Type consistency: coverage status names and fields match across Python, Prisma, Node, and frontend interfaces.
- Isolation: Gate activation remains unchanged; only BAI-KIEM subscriber semantics change. Clip generation remains exclusively request-driven.
