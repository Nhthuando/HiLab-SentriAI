import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getAreaActivityClipStatus,
  requestAreaActivityClip,
  type AreaActivityClipState,
} from '../api/areaActivities';
import type { ActivityEvidence } from '../types';

const POLL_MS = 750;

function mergeState(current: ActivityEvidence, state: AreaActivityClipState): ActivityEvidence {
  return {
    ...current,
    clipStatus: state.status,
    clipId: state.clipId,
    ...(state.message ? { message: state.message } : { message: undefined }),
  };
}

export function useDeferredEvidenceClip(initial: ActivityEvidence) {
  const [evidence, setEvidence] = useState(initial);
  const [requestError, setRequestError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const sequenceRef = useRef(0);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const apply = useCallback((state: AreaActivityClipState) => {
    setEvidence((current) => mergeState(current, state));
  }, []);

  const poll = useCallback((sequence: number) => {
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      void getAreaActivityClipStatus(initial.eventId)
        .then((state) => {
          if (sequence !== sequenceRef.current) return;
          apply(state);
          if (state.status === 'QUEUED' || state.status === 'GENERATING') poll(sequence);
        })
        .catch(() => {
          if (sequence !== sequenceRef.current) return;
          setRequestError('Không thể kiểm tra trạng thái video. Hãy thử lại.');
        });
    }, POLL_MS);
  }, [apply, clearTimer, initial.eventId]);

  const request = useCallback(async () => {
    if (!evidence.canRequestClip) return;
    clearTimer();
    setRequestError(null);
    const sequence = ++sequenceRef.current;
    setEvidence((current) => ({ ...current, clipStatus: 'QUEUED', clipId: null }));
    try {
      const state = await requestAreaActivityClip(initial.eventId);
      if (sequence !== sequenceRef.current) return;
      apply(state);
      if (state.status === 'QUEUED' || state.status === 'GENERATING') poll(sequence);
    } catch {
      if (sequence !== sequenceRef.current) return;
      setEvidence((current) => ({ ...current, clipStatus: 'FAILED', clipId: null }));
      setRequestError('Không thể bắt đầu tạo video. Hãy thử lại.');
    }
  }, [apply, clearTimer, evidence.canRequestClip, initial.eventId, poll]);

  useEffect(() => {
    setEvidence(initial);
    setRequestError(null);
    const sequence = ++sequenceRef.current;
    if (initial.clipStatus === 'QUEUED' || initial.clipStatus === 'GENERATING') poll(sequence);
    return () => {
      sequenceRef.current += 1;
      clearTimer();
    };
  }, [clearTimer, initial, poll]);

  return {
    evidence,
    request,
    requestError,
    isBusy: evidence.clipStatus === 'QUEUED' || evidence.clipStatus === 'GENERATING',
  };
}
