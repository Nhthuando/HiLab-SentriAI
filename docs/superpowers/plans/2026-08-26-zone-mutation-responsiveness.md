# Zone Mutation Responsiveness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Zone create, edit, and delete interactions immediate, correctly ordered, and cheaper against the remote Neon database.

**Architecture:** Keep optimistic UI, but route all Zone writes through a per-Zone mutation coordinator that serializes writes, coalesces rapid edits, and gives delete precedence. Send minimal API patches and replace read-before-write Prisma mutations with one direct write. Cache detection capability reads with explicit invalidation after label/model mutations.

**Tech Stack:** React 19, TypeScript 6, Vite 8, Express 4, Prisma 5, PostgreSQL/Neon, Node 24 built-in test runner.

## Global Constraints

- Do not change the V9 artifact, V9 activation, confidence thresholds, Python Worker, tracking, or zone-boundary behavior.
- Do not add a database index; existing primary/unique indexes already cover these mutations.
- Do not restore an entire camera Zone array after one failed mutation.
- Do not report a mutation as successful until the server confirms it.
- Do not create a git commit unless the user explicitly asks.

---

## File Map

- Create `backend/node-api/src/tests/test_detection_capability_cache.ts`: cache, in-flight sharing, and invalidation tests.
- Modify `backend/node-api/src/services/detectionCapabilityService.ts`: bounded cache with explicit invalidation.
- Modify `backend/node-api/src/routes/labels.ts`: invalidate capability cache after label mutations.
- Modify `backend/node-api/src/routes/trainingJobs.ts`: invalidate capability cache after model activation/return.
- Create `backend/node-api/src/repositories/ZoneMutationRepository.ts`: one-query update/delete persistence boundary.
- Create `backend/node-api/src/services/zoneMutationService.ts`: P2025/not-found semantics.
- Create `backend/node-api/src/tests/test_zone_mutation_service.ts`: direct-write and idempotent-delete tests.
- Modify `backend/node-api/src/routes/zones.ts`: use the mutation service and validate labels only when supplied.
- Create `frontend/src/domain/zoneMutationCoordinator.ts`: framework-independent per-Zone revision/queue state machine.
- Create `frontend/src/domain/zoneMutationCoordinator.test.ts`: stale-response, coalescing, create/delete race tests.
- Modify `frontend/src/api/zones.ts`: map UI patches to minimal API payloads.
- Create `frontend/src/hooks/useZoneMutations.ts`: bind the coordinator to React state and the Zone API.
- Modify `frontend/src/App.tsx`: replace ad-hoc handlers with the hook.
- Modify `frontend/src/components/Settings/ZoneEditorTab.tsx`: pending status and server-confirmed feedback.
- Modify `frontend/package.json`: add the Node test command without adding a dependency.

### Task 1: Cache Detection Capability Context Safely

**Interfaces:**

- Produces `DetectionCapabilityService.invalidate(): void`.
- Produces `invalidateDetectionContext(): void` from `detectionCapabilityService.ts`.
- `loadDetectionContext()` returns the same resolved context within 30 seconds, shares an in-flight load, and never publishes a value loaded before the latest invalidation.

- [ ] **Step 1: Write the failing cache tests**

Create `backend/node-api/src/tests/test_detection_capability_cache.ts` with an injected fake `DetectionControlRepository`. Cover:

```ts
import assert from 'node:assert/strict';
import { DetectionCapabilityService } from '../services/detectionCapabilityService';

// Call loadDetectionContext twice and assert repository methods each ran once.
// Start two unresolved loads and assert both callers receive one shared result.
// Call invalidate(), load again, and assert repository methods ran a second time.
// Invalidate while the first load is unresolved and assert that stale result is
// not cached for the next caller.
```

Use complete fake records with `id`, `vietnameseName`, `baseClass`, `_count`, `createdAt`, and `updatedAt`; return `null` for the active model.

- [ ] **Step 2: Run the cache test and verify failure**

Run:

```powershell
cd backend/node-api
npx ts-node src/tests/test_detection_capability_cache.ts
```

Expected: FAIL because `invalidate` and cached/in-flight behavior do not exist.

- [ ] **Step 3: Implement the bounded cache**

Modify `DetectionCapabilityService` to accept an optional clock/TTL and maintain a generation:

```ts
interface DetectionContextCacheOptions {
  ttlMs?: number;
  now?: () => number;
}

private cache: { value: DetectionContext; expiresAt: number; generation: number } | null = null;
private inFlight: { promise: Promise<DetectionContext>; generation: number } | null = null;
private generation = 0;

invalidate(): void {
  this.generation += 1;
  this.cache = null;
}
```

Default `ttlMs` to `30_000`. Reuse an in-flight promise only when its generation matches. Cache a resolved value only when the generation still matches. Export:

```ts
export function invalidateDetectionContext(): void {
  detectionCapabilityService.invalidate();
}
```

- [ ] **Step 4: Invalidate after capability-changing writes**

In `labels.ts`, call `invalidateDetectionContext()` immediately after successful label create/update/delete and before `currentLabelDto()` reloads the context. In `trainingJobs.ts`, invalidate after the transaction that activates a version and after returning to the base model.

- [ ] **Step 5: Run focused and existing capability tests**

Run:

```powershell
cd backend/node-api
npx ts-node src/tests/test_detection_capability_cache.ts
npx ts-node src/tests/test_label_capabilities.ts
npx ts-node src/tests/test_zone_label_validation.ts
npm run typecheck
```

Expected: all PASS.

### Task 2: Make Zone Update/Delete One-Query Mutations

**Interfaces:**

- Produces `ZoneMutationRepository.update(id, data)` and `delete(id)`.
- Produces `ZoneMutationService.update(id, data)` and `delete(id)`.
- Update of an absent Zone throws `ZoneNotFoundError`; delete of an absent Zone succeeds idempotently.

- [ ] **Step 1: Write failing service tests**

Create `backend/node-api/src/tests/test_zone_mutation_service.ts` using a fake repository:

```ts
const p2025 = Object.assign(new Error('missing'), { code: 'P2025' });

await assert.rejects(
  () => service.update('missing-id', { name: 'A' }),
  ZoneNotFoundError,
);
repository.delete = async () => { throw p2025; };
await service.delete('already-gone');
assert.equal(repository.deleteCalls, 1);
```

Also assert that successful update/delete call exactly one repository method and never call a preliminary `find` method.

- [ ] **Step 2: Run the service test and verify failure**

Run `npx ts-node src/tests/test_zone_mutation_service.ts` from `backend/node-api`.

Expected: FAIL because the repository/service do not exist.

- [ ] **Step 3: Implement the repository and service**

In `ZoneMutationRepository.ts`, define the Prisma data type and direct writes:

```ts
export interface ZoneMutationRepository {
  update(id: string, data: Prisma.ZoneUpdateInput): Promise<Zone>;
  delete(id: string): Promise<void>;
}

export class PrismaZoneMutationRepository implements ZoneMutationRepository {
  async update(id: string, data: Prisma.ZoneUpdateInput): Promise<Zone> {
    return this.client.zone.update({ where: { id }, data });
  }
  async delete(id: string): Promise<void> {
    await this.client.zone.delete({ where: { id } });
  }
}
```

In `zoneMutationService.ts`, recognize P2025 by structural `code === 'P2025'`. Translate it to `ZoneNotFoundError` for update and success for delete. Do not perform a `findUnique`.

- [ ] **Step 4: Route PUT/DELETE through the service**

Modify `zones.ts`:

- Remove `getZoneOrNull()` from PUT and DELETE.
- Keep parsing before persistence.
- Call `loadDetectionContext()` only when `input.targetLabels !== undefined`.
- Build a Prisma update object from fields actually present.
- Map `ZoneNotFoundError` on PUT to `404 ZONE_NOT_FOUND`.
- Return `204` for DELETE whether the record existed or had already disappeared.
- Preserve `P2002` as `409 ZONE_NAME_CONFLICT`.

- [ ] **Step 5: Run backend regression tests**

Run:

```powershell
cd backend/node-api
npx ts-node src/tests/test_zone_mutation_service.ts
npx ts-node src/tests/test_zone_validation.ts
npx ts-node src/tests/test_zone_label_validation.ts
npm run typecheck
npm run build
```

Expected: all PASS.

### Task 3: Build the Minimal-Payload Zone Mutation Coordinator

**Interfaces:**

- Produces `zonePatchToWrite(patch, currentZone, detectableLabels): Partial<ZoneWriteInput> | null`.
- Produces `ZoneMutationCoordinator` with `create`, `update`, `delete`, `dispose`.
- Emits `ZoneMutationStatus` values with phases `saving | saved | deleting | error`.

- [ ] **Step 1: Add the dependency-free frontend test command**

In `frontend/package.json` add:

```json
"test:zone-mutations": "node --experimental-strip-types --test src/domain/zoneMutationCoordinator.test.ts"
```

Do not add Vitest, Jest, or another package.

- [ ] **Step 2: Write failing coordinator tests**

Create `zoneMutationCoordinator.test.ts` with Node `test` and deferred promises. Cover these exact sequences:

```ts
test('three rapid edits persist only the newest queued state', async () => {});
test('delete waits behind an in-flight update and remains the final server action', async () => {});
test('a stale update response cannot replace a newer optimistic edit', async () => {});
test('deleting a temporary zone hides it and deletes the real id after create resolves', async () => {});
test('failure rolls back only the affected zone at the same revision', async () => {});
test('color-only patch performs no API call', async () => {});
```

Use an in-memory camera store and a fake API whose promises are manually resolved.

- [ ] **Step 3: Run tests and verify failure**

Run `npm run test:zone-mutations` from `frontend`.

Expected: FAIL because coordinator exports do not exist.

- [ ] **Step 4: Implement minimal payload mapping**

In `frontend/src/api/zones.ts`, export:

```ts
export function zonePatchToWrite(
  patch: Partial<PolygonZone>,
  currentZone: PolygonZone,
  detectableLabels: string[],
): Partial<ZoneWriteInput> | null;
```

Rules:

- `points` maps only to `polygonPoints`.
- `name` maps only to trimmed `name`.
- `types`, `ruleType`, or `targetLabels` recompute and include only `ruleType` and `targetLabels` using `zoneViewToWrite`.
- `color` alone returns `null`.

- [ ] **Step 5: Implement the coordinator state machine**

Create `zoneMutationCoordinator.ts` with injected API/store callbacks so no React runtime is required:

```ts
export interface ZoneMutationApi {
  create(input: ZoneWriteInput): Promise<ZoneRecord>;
  update(id: string, input: Partial<ZoneWriteInput>): Promise<ZoneRecord>;
  delete(id: string): Promise<void>;
}

export interface ZoneMutationStore {
  get(cameraId: string): PolygonZone[];
  set(cameraId: string, update: (zones: PolygonZone[]) => PolygonZone[]): void;
  status(zoneId: string, value: ZoneMutationStatus | null): void;
  notice(message: string, kind: 'success' | 'error'): void;
}
```

Use one queue record per Zone. Serialize requests for one Zone, coalesce pending updates to the latest full local state, and compare monotonically increasing revisions before applying response data or rollback. Delete removes the Zone immediately, discards unsent patches, waits for an active update, then deletes. Temporary create IDs start with `tmp-zone-`; a delete tombstone survives until create returns.

- [ ] **Step 6: Run coordinator tests**

Run `npm run test:zone-mutations`.

Expected: all six tests PASS.

### Task 4: Integrate the Coordinator into React Settings

**Interfaces:**

- Produces `useZoneMutations(options: UseZoneMutationsOptions): UseZoneMutationsResult`, returning `updateZone`, `addZone`, `deleteZone`, `statusByZoneId`, and `lastNotice`.
- `ZoneEditorTab` receives mutation status and stops emitting premature success messages.

- [ ] **Step 1: Create the React adapter hook**

Create `useZoneMutations.ts`. Keep a synchronous ref mirror of `zonesByCam`, update it inside every functional `setZonesByCam`, and adapt `createZoneRequest`, `updateZoneRequest`, and `deleteZoneRequest` to the coordinator. Dispose timers on unmount.

- [ ] **Step 2: Replace App's ad-hoc handlers**

In `App.tsx`, remove `handleUpdateZone`, `handleAddZone`, and `handleDeleteZone` rollback snapshots. Instantiate the hook with `allObjLabelNames`, `detectableObjLabelNames`, registry readiness, `zonesByCam`, and `setZonesByCam`. Pass returned handlers/status to `ZoneEditorTab`.

- [ ] **Step 3: Correct feedback in ZoneEditorTab**

- Remove immediate `Đã xóa Zone thành công` and edit-success toasts.
- Keep the optimistic canvas/list changes.
- Render `Đang lưu…` or `Đang xóa…` beside the affected Zone card.
- Show success only from the confirmed `lastNotice`.
- Clear drag refs before dispatching delete so mouse-up cannot enqueue a final stale update.
- Disable only the affected Zone's destructive button while its delete is confirmed; do not block other Zones.

- [ ] **Step 4: Build and run all focused tests**

Run:

```powershell
cd frontend
npm run test:zone-mutations
npm run build
npm run lint
cd ../backend/node-api
npm run typecheck
npm run build
```

Expected: all PASS.

### Task 5: Verify Real API Latency and Rapid User Actions

- [ ] **Step 1: Restart Node API and frontend using the user's normal commands**

Do not start a second Python Worker and do not change V9 environment values.

- [ ] **Step 2: Create one disposable Zone and measure operations**

Use a unique name `ZONE-LATENCY-CHECK-<timestamp>`. Measure a name update, geometry update, and delete. Confirm Node logs show one Prisma mutation per normal update/delete and no P2025 log spam.

- [ ] **Step 3: Exercise rapid UI sequences**

Perform update-update-update, drag-then-delete, repeated delete, add-then-immediate-delete, and simultaneous edits on two Zones. Confirm:

- UI changes immediately.
- `Đang lưu…` remains until confirmation.
- No deleted Zone reappears.
- Latest edit wins after refresh.
- Another Zone never rolls backward.

- [ ] **Step 4: Clean up only the disposable Zone and report before/after timings**

Do not alter user Zones. Include measured request times and confirm the V9 artifact/configuration was untouched.
