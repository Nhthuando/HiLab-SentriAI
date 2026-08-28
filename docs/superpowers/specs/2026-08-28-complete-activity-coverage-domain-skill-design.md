# Complete BAI-KIEM Activity Coverage and Domain Skill Design

## Status

- Design direction approved by Hữu Thuận in chat on 2026-08-28 after user acceptance exposed an incomplete truck count.
- This specification corrects the coverage assumptions in `2026-08-27-area-activity-analytics-qa-design.md` and extends `VS-QA-CHAT`.
- Existing Gate, violation, training, zone, chat-history, and lazy-clip behavior must remain backward compatible.

## Problem statement

The answer “hôm nay có 1 lượt xe tải” was generated from one persisted `truck` activity session created while only part of the local BAI-KIEM video was processed. The video contains more visible trucks. The current worker pauses Area inference whenever no live-feed subscriber exists, so database rows are not a complete representation of the source. Persisted chat answers are immutable snapshots and do not update when more video is processed or activity history is reset.

The runtime also has a TypeScript system prompt and function tools but no project-owned domain `SKILL.md`. Consequently, counting semantics, detector taxonomy, coverage rules, evidence rules, and safe answer wording are split across code and are not maintained as one domain policy.

## Goals

1. Process BAI-KIEM analytics independently of whether a user is viewing the camera.
2. For a local video, eventually cover the complete source and persist metadata sessions without eagerly creating images or MP4 files.
3. Make coverage explicit so AI never presents a partial count as a complete-day fact.
4. Preserve local replay idempotency: completing another loop never increments or recalculates an existing session.
5. Create a standard project domain skill and load that exact file into Gemini system instructions.
6. Verify the complete test video against a reviewed ground-truth manifest, including the user's observation of more than three truck appearances.

## Non-goals

- Identifying unique physical assets without a stable asset ID or license plate.
- Generating clips during detection or indexing.
- Replacing function calling with free-form SQL.
- Rewriting Gate or Area violation behavior.
- Retroactively rewriting stored assistant messages.
- Automatically deleting old activity rows after a detector, zone, or skill update.

## Considered approaches

### A. Keep subscriber-driven inference and improve wording only

This is cheap but cannot produce complete statistics. It only makes an incomplete result more honest and does not meet the requested count accuracy.

### B. Add a second offline detector/indexer

A separate scanner can run faster than playback, but loading another detector duplicates GPU memory, risks model/config drift, and creates concurrency around the same activity tables.

### C. Decouple analytics from frame viewing in the existing Area pipeline — selected

The existing Area pipeline continues one inference pass at its configured FPS even without a viewer. Subscriber state controls feed emission demand, not analytics. Local files loop as they do today; the first complete coverage is built incrementally and later loops are deduplicated. This keeps one detector, one tracker, one zone snapshot, and one persistence path.

For the MVP, the local video continues at the existing playback pace. Accuracy and isolation take priority over a second high-speed inference path. A future explicit fast-index job may be added only after GPU/load benchmarking.

## Runtime activation design

### Separate states

`AreaPipeline` owns two independent states:

- `analytics_enabled`: whether frames are read, inferred, tracked, and persisted. It defaults to true after successful worker preparation for BAI-KIEM and remains true when the last UI viewer disconnects.
- `viewer_active`: whether a live-feed subscriber currently needs rendered frame emission. It is controlled by the existing activation endpoint.

The worker loop runs while `analytics_enabled` is true. Activity and violation transitions are always queued. Rendered frames are emitted only when `viewer_active` is true; event and alert delivery remains unchanged.

Gate behavior is not changed by this specification. The activation endpoint keeps its existing response shape and reports both effective analytics and viewer state additively for BAI-KIEM.

### Local file lifecycle

- Start analytics after the detector and first valid zone/label snapshot are ready.
- Continue from the server-owned current source position.
- At EOF, close open sessions, rewind, and continue.
- Manual seek closes current sessions and starts a new coverage interval; it never marks skipped time as processed.
- Worker restart resumes coverage from persisted intervals; replay fingerprints prevent duplicate sessions.
- Area history reset deletes activity rows and coverage state together. It does not delete chat, Gate data, source media, or generated model artifacts.

### Live source lifecycle

For RTSP/live sources, `analytics_enabled` stays true while the camera is configured and available. Coverage is expressed as observed wall-clock intervals, not a percentage. A disconnect creates a gap that AI must disclose.

## Coverage model

Extend `area_activity_collection_state` additively:

| Field | Meaning |
|---|---|
| `sourceKind` | `LOCAL_FILE`, `LIVE`, or `UNAVAILABLE` |
| `sourceFingerprint` | Stable hash of server-owned source identity, file size, and modification time; never contains credentials |
| `sourceDurationSeconds` | Local media duration; null for live sources |
| `coveredIntervals` | Normalized, merged half-open source-time intervals for the active local fingerprint |
| `coveragePercent` | Derived persisted snapshot in the range 0–100 |
| `completedAt` | First time coverage reaches the complete threshold |
| `coverageStatus` | `NOT_STARTED`, `PARTIAL`, `COMPLETE`, `STALE`, or `UNAVAILABLE` |
| `lastObservedAt` | Latest successfully processed frame time |

Coverage intervals are merged in memory and persisted at a bounded cadence and on seek/EOF/shutdown. Adjacent intervals within one effective inference step merge. Completion requires the merged union to cover at least 99% of the local duration and to include both the beginning and end tolerances; a manual jump from the middle to EOF cannot mark the source complete.

If `sourceFingerprint` changes, start a new coverage ledger. Existing activity sessions remain auditable but are excluded from current-source summaries unless their `sourceRef` matches the active source. No historical row is fabricated or recalculated.

## QA counting contract

`get_area_activity_summary` and `get_area_activity_sessions` return a coverage object containing status, percent, source duration, covered intervals, last observation, and active source identity token. Summary queries filter local sessions to the active `sourceRef` by default.

Answer rules:

- `COMPLETE`: the AI may say “đã ghi nhận tổng cộng N lượt trong toàn bộ video nguồn”.
- `PARTIAL`: the AI must say “hiện mới ghi nhận N lượt trong X% video đã xử lý” and must not state that N is the full-day/video total.
- `NOT_STARTED`, `STALE`, or `UNAVAILABLE`: explain that a reliable total is unavailable.
- Stored chat answers remain point-in-time records. A new question performs a new database query.
- Count language is always `lượt vào zone`, not unique vehicles.
- “Xe tải” maps only to canonical `truck`. “Xe nâng” maps to `forklift + reach_stacker`.
- Recent evidence is selected deterministically from the matching sessions; clip status never changes the count.

The API may return exact metadata totals even during partial coverage, but every consumer receives the coverage status. The frontend displays a compact coverage line beneath activity answers so correctness does not depend solely on model wording.

## Project domain skill

### Canonical artifact

Create `backend/node-api/src/ai/domain/sentriai-operations/SKILL.md` with only `name` and `description` in YAML frontmatter. Keep the body concise and imperative. Include:

- SentriAI scope and saved-data-only boundary;
- camera and zone terminology;
- canonical object taxonomy and Vietnamese aliases;
- activity count semantics;
- complete/partial/stale coverage policy;
- date/timezone policy;
- allowed/violation/open/closed semantics;
- evidence and lazy-clip rules;
- privacy and non-invention rules;
- deterministic response templates and representative questions.

Use references only if the main file approaches 500 lines. No README, changelog, or duplicate prompt document is added.

### Runtime loading

Add a focused loader that:

1. resolves the skill from the Node workspace in both `ts-node` and compiled `dist` execution;
2. validates required frontmatter fields and required policy headings;
3. strips only the YAML frontmatter and returns the body verbatim;
4. caches by absolute path plus modification time;
5. fails application startup with a sanitized configuration error if the skill is missing or invalid.

`prompts.ts` combines the small stable Gemini safety preamble with the loaded skill body. Domain rules must not be copied into both TypeScript and Markdown. Tool declarations remain code-owned because they are executable contracts.

Although the file follows the standard Skill format, Gemini does not discover it automatically. Explicit runtime loading is mandatory and covered by tests.

## Error and compatibility behavior

- Database or coverage-write failure must not stop rendered video or existing violation alerts; coverage becomes stale and the AI cannot claim completeness.
- A feed viewer disconnect must never pause BAI-KIEM analytics.
- A source read failure preserves prior intervals and marks coverage stale/unavailable until recovery.
- Duplicate replay delivery must leave row count and every existing session timestamp/duration/`updatedAt` unchanged.
- Clip status remains `NOT_REQUESTED` until an explicit `Xem video` request.
- Existing `GET /area-activities`, QA, chat, Gate clips, violation clips, and WebSocket payload fields remain compatible; coverage/viewer fields are additive.
- Domain skill content and errors never expose filesystem paths, database URLs, RTSP credentials, Gemini keys, or stack traces to clients.

## Verification

### Ground truth

Create a reviewed manifest for `KiemHoa-LM06_fastseek.mp4` containing each visible truck zone-entry interval and expected policy result. Store source-relative time ranges and zone, not copied video frames. The manifest is the acceptance oracle; “more than three” is a lower-bound observation until exact annotation is complete.

### Python

- Verify analytics continues after `viewer_active=false` while frame emission stops.
- Verify viewer reconnect does not reset tracker or coverage.
- Verify interval merge, manual seek gaps, EOF completion, restart resume, source change, and live gaps.
- Process the complete real video and compare persisted truck sessions to the reviewed manifest.
- Run a second complete loop and assert zero inserts and zero changed existing rows.
- Assert no clip file/status transition occurs during either loop.
- Run all existing Area/tracker/violation tests.

### Node and Gemini

- Validate and load the real `SKILL.md` in dev and compiled layouts.
- Fail tests for missing frontmatter, missing coverage policy, and missing file.
- Verify activity tools filter to the active source and return coverage.
- Verify deterministic routing for truck, forklift group, car, person, and reach stacker.
- With synthetic tool results, verify partial answers contain percent/incomplete wording and complete answers contain a complete-source claim.
- Run focused QA tests, typecheck, build, and existing API regressions.

### Frontend and end-to-end

- Display partial/complete/stale coverage from structured response data.
- Reload chat and make clear that stored answers are historical snapshots.
- On the real source, wait for `COMPLETE`, ask the truck question, and compare the answer count with the manifest.
- Click one evidence item and verify `NOT_REQUESTED -> QUEUED/GENERATING -> READY`; confirm no other session receives a clip.
- Verify Gate, Area monitor, zones, history, copy, and error states are unchanged.

## Acceptance criteria

- [ ] BAI-KIEM activity analytics runs without a live-feed subscriber.
- [ ] The full local source reaches `COMPLETE` coverage without eager clip creation.
- [ ] The reviewed real-video truck manifest and persisted truck session count match exactly.
- [ ] A second loop changes neither count nor existing session values.
- [ ] Partial coverage can never be worded as a complete total.
- [ ] The frontend exposes coverage status for activity answers.
- [ ] A valid project domain `SKILL.md` exists and is loaded verbatim into Gemini runtime instructions.
- [ ] Skill loader, coverage, full-video, replay, lazy-clip, QA, build, and regression gates pass.
- [ ] No unrelated Gate, violation, zone, training, or chat-history behavior regresses.

## Rollout

1. Apply the additive coverage migration.
2. Deploy the worker activation/coverage changes with the existing activity writer disabled only if migration is absent.
3. Deploy the Node skill loader and coverage-aware tools/prompts.
4. Deploy the additive frontend coverage indicator.
5. Reset only BAI-KIEM activity/coverage test data, run one full source pass, review ground truth, then run the replay pass.
6. Keep all clips lazy and request one evidence clip only during explicit acceptance.

Rollback disables continuous BAI-KIEM analytics and the coverage-aware QA addition without removing sessions or changing Gate/violation contracts. The previous prompt cannot be restored without also disabling complete-total claims, because subscriber-driven coverage is not trustworthy.
