import type { PrismaClient } from '@prisma/client';
import { prisma } from '../prisma/client';
import {
  AreaEventClipUnavailableError,
  getAreaEventClip,
  requestAreaEventClip,
  type AreaClipStatus,
} from './areaEventClipService';

export interface AreaActivityClipState {
  activityId: string;
  status: AreaClipStatus;
  clipId: string | null;
  clipUrl: string | null;
  message?: string;
}

function workerUrl(): string {
  return (process.env.PYTHON_WORKER_HTTP_URL || 'http://localhost:8001').replace(/\/+$/, '');
}

function decodeWorkerState(activityId: string, value: unknown): AreaActivityClipState {
  if (!value || typeof value !== 'object') {
    throw new AreaEventClipUnavailableError('Python worker returned an invalid activity clip response');
  }
  const candidate = value as Record<string, unknown>;
  const allowed = new Set<AreaClipStatus>([
    'NOT_REQUESTED', 'QUEUED', 'GENERATING', 'READY', 'FAILED', 'EXPIRED',
  ]);
  if (candidate.activityId !== activityId || typeof candidate.status !== 'string'
    || !allowed.has(candidate.status as AreaClipStatus)) {
    throw new AreaEventClipUnavailableError('Python worker returned an invalid activity clip response');
  }
  const status = candidate.status as AreaClipStatus;
  return {
    activityId,
    status,
    clipId: status === 'READY' ? activityId : null,
    clipUrl: status === 'READY' ? `/api/v1/clips/${encodeURIComponent(activityId)}/stream` : null,
    ...(typeof candidate.message === 'string' ? { message: candidate.message } : {}),
  };
}

async function callWorker(activityId: string, method: 'GET' | 'POST', fetchImpl: typeof fetch): Promise<AreaActivityClipState> {
  try {
    const response = await fetchImpl(
      `${workerUrl()}/cameras/BAI-KIEM/activities/${encodeURIComponent(activityId)}/clip`,
      { method, headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(5000) },
    );
    if (!response.ok) {
      throw new AreaEventClipUnavailableError(`Python worker rejected activity clip request with HTTP ${response.status}`);
    }
    return decodeWorkerState(activityId, await response.json());
  } catch (error) {
    if (error instanceof AreaEventClipUnavailableError) throw error;
    throw new AreaEventClipUnavailableError('Python worker is unavailable for activity clip generation', { cause: error });
  }
}

async function linkedViolationId(activityId: string, client: PrismaClient): Promise<string | null> {
  const activity = await client.areaActivitySession.findFirst({
    where: { id: activityId, cameraId: 'BAI-KIEM' },
    select: { violationId: true },
  });
  return activity?.violationId ?? null;
}

function fromViolation(activityId: string, violationId: string, state: Awaited<ReturnType<typeof getAreaEventClip>>): AreaActivityClipState {
  return {
    activityId,
    status: state.status,
    clipId: state.status === 'READY' ? violationId : null,
    clipUrl: state.status === 'READY' ? `/api/v1/clips/${encodeURIComponent(violationId)}/stream` : null,
    ...(state.message ? { message: state.message } : {}),
  };
}

export async function requestAreaActivityClip(
  activityId: string,
  client: PrismaClient = prisma,
  fetchImpl: typeof fetch = fetch,
): Promise<AreaActivityClipState> {
  const violationId = await linkedViolationId(activityId, client);
  if (violationId) return fromViolation(activityId, violationId, await requestAreaEventClip(violationId, fetchImpl));
  return callWorker(activityId, 'POST', fetchImpl);
}

export async function getAreaActivityClip(
  activityId: string,
  client: PrismaClient = prisma,
  fetchImpl: typeof fetch = fetch,
): Promise<AreaActivityClipState> {
  const violationId = await linkedViolationId(activityId, client);
  if (violationId) return fromViolation(activityId, violationId, await getAreaEventClip(violationId, fetchImpl));
  return callWorker(activityId, 'GET', fetchImpl);
}
