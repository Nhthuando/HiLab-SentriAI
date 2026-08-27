# Monitor UI and Annotation Source Fixes

## Goal

Fix three frontend regressions without changing the camera, detection, event, or persistence behavior:

- Make the GATE video controls match BAI-KIEM.
- Remove built-in annotation images and samples that the user never uploaded.
- Keep monitor controls readable in both dark and light themes.

## GATE playback controls

`GateMonitor` will keep its current millisecond playback API and polling behavior. The UI will add the same controls and layout used by BAI-KIEM:

- A pause/resume button beside the timestamp.
- `-10s`, pause/resume, and `+10s` controls beside the seek slider.
- Current and total video time in the same control group.

Pause is display-only, matching the existing BAI-KIEM behavior. It freezes the current frame and detections in React while the WebSocket and backend AI pipeline continue normally. Seeking stays bounded between zero and the video duration and continues to use the existing GATE seek endpoint.

## Annotation sources

The frontend will no longer initialize annotation state with `INITIAL_ANN_SOURCES` or `INITIAL_ANN_SAMPLES`. The media API remains the source of truth for uploaded files.

On startup, the frontend will remove only the two known legacy demo records (`src1` and `src2` when marked as defaults) from local storage. It will not delete or filter user-uploaded media returned by the server. `ObjectLabelTab` will support an empty source list and show an upload prompt instead of dereferencing a missing source.

## Theme behavior

Monitor status bars and neutral playback buttons will use semantic theme tokens such as `var(--ink)`, `var(--ink2)`, and `var(--raise)` instead of white text or translucent white backgrounds. Text that sits on a solid accent-colored button may remain white for contrast.

## Scope boundaries

No Python worker, Node API, database schema, event logic, detector configuration, LPR behavior, or stream protocol will change. Existing BAI-KIEM pause and seek behavior will remain unchanged apart from theme-safe colors.

## Verification

- Run the frontend production build.
- Run frontend lint.
- Run Node typecheck if shared TypeScript types are touched.
- Confirm no conflict markers or unstaged implementation changes remain.
- Inspect the final diff to ensure backend and AI files are unaffected by this fix.
