# V9 Portable Fallback Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the committed V9 artifact load consistently on a second machine from approved `CUSTOM_AUGMENT_*` settings without requiring a copied `ACTIVE` database row.

**Architecture:** Preserve database-first selection and the failed automatic quality result. Add one hash-bound canonical manual-approval predicate in each runtime, use it only for the configured fallback, and keep every existing fail-closed artifact, base-regression, path, label, and runtime check.

**Tech Stack:** Python 3.12, `unittest`, Node.js, TypeScript, `ts-node`, Ultralytics artifact metadata

## Global Constraints

- Do not change `qualityGate.passed` or claim that V9 passed automatic acceptance.
- Do not alter, create, or activate database model-version rows.
- Do not retrain, replace, or modify the V9 checkpoint.
- Do not weaken checksum, base-regression, path-containment, label-map, or runtime-mode validation.
- An `ACTIVE` database model continues to win over the configured fallback.
- A failed quality gate is bypassed only with both environment opt-ins and a canonical owner approval bound to the configured artifact SHA-256.

---

## File Structure

- `backend/python-worker/zone/zone_sync.py`: validate canonical manual-production approval for the worker fallback.
- `backend/python-worker/tests/test_zone_sync_capabilities.py`: cover accepted approval, missing opt-in, legacy metadata, and approval-hash mismatch.
- `backend/node-api/src/services/detectionCapabilityService.ts`: apply the equivalent approval predicate to Node capability fallback selection.
- `backend/node-api/src/tests/test_label_capabilities.ts`: unit-test the predicate and verify the committed V9 fallback is surfaced by the service.

### Task 1: Python worker fallback approval

**Files:**
- Modify: `backend/python-worker/zone/zone_sync.py:136-237`
- Test: `backend/python-worker/tests/test_zone_sync_capabilities.py:184-245`

**Interfaces:**
- Consumes: evaluation JSON as `Mapping[str, Any]`, configured artifact SHA-256 as `str`, and `CUSTOM_AUGMENT_MANUAL_CANDIDATE` from the supplied environment mapping.
- Produces: `_has_configured_manual_approval(evaluation: Mapping[str, Any], expected_sha256: str) -> bool`, used by `_configured_custom_model`.

- [x] **Step 1: Replace the legacy-positive fixture with canonical approval and add negative cases**

```python
approval = {
    "approved": True,
    "allowPartialUnified": True,
    "artifactSha256": artifact_sha256,
}
evaluation = {
    "manualProductionApproval": approval,
    "runtimeMode": "UNIFIED",
    "qualityGate": {"passed": False},
    "baseRegression": {"passed": True},
}
```

Assert that the fallback is rejected without `CUSTOM_AUGMENT_MANUAL_CANDIDATE`, accepted with it, rejected when only `manualTestApproved` is present, and rejected when `manualProductionApproval.artifactSha256` differs from the configured hash.

- [x] **Step 2: Run the focused Python test and verify the canonical positive case fails**

Run:

```powershell
backend\python-worker\.venv\Scripts\python.exe -m unittest backend.python-worker.tests.test_zone_sync_capabilities.ZoneSynchronizerCapabilityTests.test_manual_candidate_requires_metadata_and_environment_opt_in -v
```

Expected: FAIL because `_configured_custom_model` still checks `manualTestApproved`.

- [x] **Step 3: Implement the hash-bound canonical approval predicate**

```python
def _has_configured_manual_approval(
    evaluation: Mapping[str, Any],
    expected_sha256: str,
) -> bool:
    approval = evaluation.get("manualProductionApproval")
    if not isinstance(approval, dict):
        return False
    approval_sha256 = approval.get("artifactSha256")
    return (
        approval.get("approved") is True
        and approval.get("allowPartialUnified") is True
        and isinstance(approval_sha256, str)
        and approval_sha256.casefold() == expected_sha256
    )
```

Use it in `manual_candidate` together with the existing environment opt-in. Do not change the passing-quality path, base-regression check, file checksum check, or returned approval metadata.

- [x] **Step 4: Run the full Python capability test file**

Run:

```powershell
backend\python-worker\.venv\Scripts\python.exe -m unittest backend.python-worker.tests.test_zone_sync_capabilities -v
```

Expected: all tests PASS, including canonical approval, legacy rejection, and approval-hash rejection.

- [x] **Step 5: Commit the Python change**

```powershell
git add backend/python-worker/zone/zone_sync.py backend/python-worker/tests/test_zone_sync_capabilities.py
git commit -m "fix: accept canonical v9 fallback approval in worker"
```

### Task 2: Node capability fallback approval

**Files:**
- Modify: `backend/node-api/src/services/detectionCapabilityService.ts:29-90`
- Test: `backend/node-api/src/tests/test_label_capabilities.ts`

**Interfaces:**
- Consumes: parsed evaluation metrics as `unknown` and the configured artifact SHA-256 as `string`.
- Produces: `hasConfiguredManualApproval(metrics: unknown, expectedSha256: string): boolean`, exported for focused deterministic tests and used by `configuredModelContext`.

- [ ] **Step 1: Add deterministic predicate tests and a service-level V9 fallback assertion**

```typescript
assert.equal(hasConfiguredManualApproval({
  manualProductionApproval: {
    approved: true,
    allowPartialUnified: true,
    artifactSha256: 'a'.repeat(64),
  },
}, 'a'.repeat(64)), true);
assert.equal(hasConfiguredManualApproval({ manualTestApproved: true }, 'a'.repeat(64)), false);
assert.equal(hasConfiguredManualApproval({
  manualProductionApproval: {
    approved: true,
    allowPartialUnified: true,
    artifactSha256: 'b'.repeat(64),
  },
}, 'a'.repeat(64)), false);
```

Temporarily set the committed V9 `CUSTOM_AUGMENT_*` values, construct `DetectionCapabilityService` with a repository returning no active model, assert `activeModel.versionKey === 'baikiem-v9-unified-candidate-final'`, and restore every modified environment value in `finally`.

- [ ] **Step 2: Run the Node capability test and verify it fails**

Run:

```powershell
Set-Location backend/node-api
npx ts-node src/tests/test_label_capabilities.ts
```

Expected: FAIL because the new predicate is absent or the committed fallback remains rejected by the legacy field check.

- [ ] **Step 3: Implement the Node predicate and wire it into fallback selection**

```typescript
export function hasConfiguredManualApproval(metrics: unknown, expectedSha256: string): boolean {
  if (!hasOwnerApprovedPartialUnified(metrics)) return false;
  const approval = (metrics as Record<string, unknown>).manualProductionApproval as Record<string, unknown>;
  return typeof approval.artifactSha256 === 'string'
    && approval.artifactSha256.toLowerCase() === expectedSha256;
}
```

Replace `metrics.manualTestApproved === true` with `hasConfiguredManualApproval(metrics, expectedSha256)`. Preserve the existing `hasOwnerApprovedPartialUnified` behavior for database-backed partial unified models.

- [ ] **Step 4: Run Node tests and type checking**

Run:

```powershell
Set-Location backend/node-api
npx ts-node src/tests/test_label_capabilities.ts
npm run typecheck
```

Expected: capability tests and TypeScript type checking PASS.

- [ ] **Step 5: Commit the Node change**

```powershell
git add backend/node-api/src/services/detectionCapabilityService.ts backend/node-api/src/tests/test_label_capabilities.ts
git commit -m "fix: align node v9 fallback approval schema"
```

### Task 3: Cross-runtime verification and handoff

**Files:**
- Verify: `backend/data/training/models/baikiem-v9-unified-candidate-final/evaluation.json`
- Verify: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt`

**Interfaces:**
- Consumes: committed V9 metadata, artifact, and approved non-secret environment settings.
- Produces: evidence that Python and Node accept the same canonical approval without modifying artifact or database state.

- [ ] **Step 1: Run the worker's real configured-model diagnostic**

Run:

```powershell
Set-Location backend/python-worker
.\.venv\Scripts\python.exe -c "import os, main; from zone.zone_sync import _configured_custom_model; model=_configured_custom_model(); print(os.getenv('CUSTOM_AUGMENT_VERSION_KEY')); print(None if model is None else model['version_key'])"
```

Expected: both printed version keys equal `baikiem-v9-unified-candidate-final`.

- [ ] **Step 2: Verify the committed checkpoint hash and repository diff**

Run:

```powershell
Get-FileHash backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt -Algorithm SHA256
git diff --check
git status --short
```

Expected: SHA-256 is `3772E978FC4635A6A2D3DFFB59286BD89C0EBBC6CC6E27DC77532B5006EAAB52`, `git diff --check` is clean, and only intended plan/code/test changes are present before their commits.

- [ ] **Step 3: Report rollout instructions**

The second machine pulls the implementation commits, retains the same non-secret `CUSTOM_AUGMENT_*` values, fully stops the old Python worker and Node API, and restarts them. Startup evidence must contain `Loaded ACTIVE custom model baikiem-v9-unified-candidate-final` and `Area detection control applied: mode=UNIFIED`.
