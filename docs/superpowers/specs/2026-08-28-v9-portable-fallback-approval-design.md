# V9 Portable Fallback Approval Design

**Date:** 2026-08-28  
**Status:** Approved for planning  
**Scope:** Python Area worker and Node detection-capability fallback selection

## Problem

The reviewed V9 artifact is committed and its checksum is valid, but a second machine cannot load it from `backend/.env` when its database has no `ACTIVE` model-version row. The fallback rejects the artifact because `qualityGate.passed` is intentionally `false` and both runtimes still look for the obsolete top-level field `manualTestApproved`.

The canonical V9 metadata instead records the owner's decision under `manualProductionApproval`. The database activation path already understands that structure, so database-backed machines can run V9 while clean machines using the configured fallback cannot.

## Goal

A machine that pulls the same commit, has the same V9 artifact, and uses the approved `CUSTOM_AUGMENT_*` environment settings can load V9 without copying another machine's database state. Python runtime selection and Node capability reporting must make the same decision.

## Non-goals

- Do not change `qualityGate.passed` or claim that V9 passed automatic acceptance.
- Do not alter, create, or activate database model-version rows.
- Do not retrain, replace, or modify the V9 checkpoint.
- Do not weaken checksum, base-regression, path-containment, label-map, or runtime-mode validation.

## Design

The existing precedence remains unchanged: an `ACTIVE` database model wins, and the configured fallback is considered only when the database returns no active model.

The configured fallback may bypass the failed automatic quality gate only when all of these conditions hold:

1. `CUSTOM_AUGMENT_FORCE_DEFAULT` is enabled.
2. `CUSTOM_AUGMENT_MANUAL_CANDIDATE` is enabled.
3. `manualProductionApproval` is an object with `approved: true`.
4. `manualProductionApproval.allowPartialUnified` is `true`.
5. `manualProductionApproval.artifactSha256` equals the configured artifact SHA-256.
6. The artifact's computed SHA-256 equals the configured SHA-256.
7. The saved base-regression gate passed.

The obsolete `manualTestApproved` field will not be added to the evaluation artifact and will no longer authorize the configured fallback. This keeps one canonical approval schema.

Python and Node will implement equivalent predicates. The accepted fallback metadata will continue to carry `manualProductionApproval` so partial unified coverage is authorized consistently downstream.

## Failure behavior

Validation remains fail-closed. Missing approval fields, a false approval, missing partial-coverage authorization, a mismatched approval hash, a mismatched file hash, unreadable metadata, a failed base-regression gate, or disabled environment opt-in all disable the configured custom model. Base COCO detection remains available according to the current rollback behavior.

## Tests

Python and Node regression tests will cover:

- accepted canonical owner approval with a failed automatic quality gate;
- rejection when manual-candidate environment opt-in is disabled;
- rejection when owner approval is absent or false;
- rejection when `allowPartialUnified` is false;
- rejection when the approval artifact hash differs from the configured/checkpoint hash;
- continued rejection of the obsolete `manualTestApproved` field by itself;
- unchanged precedence of an `ACTIVE` database model over the configured fallback where existing tests cover selection.

Targeted Python and Node tests will run after implementation, followed by the relevant broader test files and type checking.

## Rollout

The code and tests are committed and pushed from the primary repository. The second machine pulls the commit, retains the approved non-secret `CUSTOM_AUGMENT_*` settings, and fully restarts the Python worker and Node API. Successful startup must report V9 as the loaded `UNIFIED` model; no database synchronization is required.
