# Object Detection Training UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mock-only, accessible inline training lifecycle panel to Settings → Object Labels without changing the existing label/import/save workflow.

**Architecture:** Keep all mock job/version state local to a focused `ObjectTrainingPanel` child component. `ObjectLabelTab` derives sample and label coverage from its existing props and passes a read-only readiness summary to the child. No API module, App state, backend contract, persistence or database migration changes occur in this UI-design batch.

**Tech Stack:** React 19, TypeScript, Vite 8, existing inline-token styling, lucide-react already installed.

## Global Constraints

- Reuse `frontend/` and existing Modern Industrial tokens; add no dependency.
- This is mock UI only: no fetch, WebSocket, API route, database or Python worker call.
- Saving annotation samples must never create or transition a training job.
- Area monitoring has priority: `PAUSED_GPU` must be distinct from failure and explain the 8 FPS guard.
- Candidate activation is explicit and keyboard-accessible; a candidate must show quality and FPS before activation.
- Preserve image/video import, video scrubber, box editing, label saving and zone-label workflow.

---

## File Structure

- Create `frontend/src/components/Settings/ObjectTrainingPanel.tsx` — isolated presentation/state machine for mock readiness, training, candidate review, activation and rollback.
- Modify `frontend/src/components/Settings/ObjectLabelTab.tsx` — compute read-only sample/label/source readiness from existing props and mount the panel below existing sample controls.
- Modify `frontend/src/types.ts` — add frontend-only `TrainingReadiness`, `MockTrainingJob` and `MockModelVersion` interfaces used only by the new component.
- Modify `docs/design/ui-to-frontend-handoff.md` only after browser review and explicit final UI approval; this plan does not authorize that update yet.

### Task 1: Define training UI data contracts and the isolated mock panel

**Files:**
- Create: `frontend/src/components/Settings/ObjectTrainingPanel.tsx`
- Modify: `frontend/src/types.ts` after `AnnotationSample`
- Test: Vite TypeScript build and browser interaction checks; no unit-test runner is configured in `frontend/package.json`, so do not introduce one in this bounded UI batch.

**Interfaces:**
- Consumes: `TrainingReadiness { savedSamples: number; labelsWithSamples: number; sourceCount: number; excludedSamples: number; isReady: boolean }`.
- Produces: `ObjectTrainingPanel` React component with no callback props; its job/version state stays mock-local.
- States: `idle`, `queued`, `running`, `paused_gpu`, `evaluating`, `candidate`, `active`, `failed`.

- [ ] **Step 1: Add the frontend-only types**

```ts
export interface TrainingReadiness {
  savedSamples: number;
  labelsWithSamples: number;
  sourceCount: number;
  excludedSamples: number;
  isReady: boolean;
}

export type MockTrainingStatus =
  | 'idle' | 'queued' | 'running' | 'paused_gpu'
  | 'evaluating' | 'candidate' | 'active' | 'failed';
```

- [ ] **Step 2: Implement the panel state transitions and semantic controls**

```tsx
const [status, setStatus] = useState<MockTrainingStatus>('idle');
const [showActivateConfirm, setShowActivateConfirm] = useState(false);

const startTraining = () => {
  if (!readiness.isReady) return;
  setStatus('queued');
  window.setTimeout(() => setStatus('running'), 350);
};
```

Render readiness counts, an explanatory disabled Train button, `aria-live="polite"` status copy, a visible `PAUSED_GPU` amber guard, mock epoch/progress, held-out overall mAP, forklift mAP and benchmark FPS. Use a native confirmation dialog/card before `Activate`, and include an equivalent confirmation before rollback.

- [ ] **Step 3: Run the type/build check**

Run: `npm.cmd run build` from `frontend/`.

Expected: TypeScript accepts the new interfaces and component; Vite emits the production bundle.

- [ ] **Step 4: Manually check panel states in browser**

Run the Vite dev server and verify, through visible controls, disabled readiness, start, GPU pause/resume presentation, candidate confirmation and rollback confirmation. Capture no screenshots unless the user asks.

- [ ] **Step 5: Do not commit**

The shared workspace is in an unresolved merge and the user has not authorized a commit. Record build/browser evidence in the later Team1 task instead.

### Task 2: Integrate the panel without changing the annotation flow

**Files:**
- Modify: `frontend/src/components/Settings/ObjectLabelTab.tsx` near `pendingSessionCount` and the existing right-column/sample area
- Test: `frontend/` build plus browser regression of label import, frame scrubber, draw/save, and new panel controls

**Interfaces:**
- Consumes: `annSamples: AnnotationSample[]`, `objLabels: ObjectLabel[]`, `sources: AnnotationSource[]`, `ObjectTrainingPanel` and `TrainingReadiness`.
- Produces: A `readiness` value whose `savedSamples` excludes `session === 1` unsaved boxes; no changes to `onSaveSamples` or parent props.

- [ ] **Step 1: Derive readiness only from saved annotation data**

```ts
const savedSamples = annSamples.filter((sample) => sample.session !== 1);
const readiness: TrainingReadiness = {
  savedSamples: savedSamples.length,
  labelsWithSamples: new Set(savedSamples.map((sample) => sample.labelId)).size,
  sourceCount: new Set(savedSamples.map((sample) => sample.srcId)).size,
  excludedSamples: 0,
  isReady: savedSamples.length >= 20 && new Set(savedSamples.map((sample) => sample.labelId)).size >= 2,
};
```

This threshold is a mock readiness gate, not an accuracy guarantee and not a replacement for backend validation/export.

- [ ] **Step 2: Mount the child below existing sample save/list controls**

```tsx
<ObjectTrainingPanel readiness={readiness} />
```

Do not alter `handleSave`, `onSaveSamples`, media import, video time state, source delete behavior, box drawing, keyboard label selection or modal label CRUD.

- [ ] **Step 3: Run regression build**

Run: `npm.cmd run build` from `frontend/`.

Expected: Exit code 0 with no TypeScript error.

- [ ] **Step 4: Run browser regression**

At desktop and a narrow mobile viewport, open Settings → Object Labels. Import/select existing media, move the video scrubber if the source is video, draw a box, save it, and verify that only readiness changes. Verify no training state starts until the explicit Train button is pressed.

- [ ] **Step 5: Request final visual approval before writing the handoff**

Provide the local URL, exact route/tab instructions, and state that the UI-to-frontend handoff remains unchanged until the user explicitly approves the live mock.

## Self-Review

- Spec coverage: Task 1 covers readiness, status, GPU guard, quality/FPS metrics, activation/rollback and accessibility. Task 2 covers integration and protects all existing labeling requirements.
- No API or backend code is planned; the explicit production gap is preserved.
- No test framework is added because none exists in the frontend manifest; build plus browser checks are the available proportionate evidence.
- Type names and the `ObjectTrainingPanel` prop are declared consistently across tasks.
