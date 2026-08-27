export type AreaClipStatus =
  | 'NOT_REQUESTED'
  | 'QUEUED'
  | 'GENERATING'
  | 'READY'
  | 'FAILED'
  | 'EXPIRED';

export interface AreaClipState {
  violationId: string;
  status: AreaClipStatus;
  clipUrl: string | null;
  message?: string;
}

const CLIP_STATUSES = new Set<AreaClipStatus>([
  'NOT_REQUESTED',
  'QUEUED',
  'GENERATING',
  'READY',
  'FAILED',
  'EXPIRED',
]);

export class AreaEventClipUnavailableError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = 'AreaEventClipUnavailableError';
  }
}

function getPythonWorkerHttpUrl(): string {
  return (process.env.PYTHON_WORKER_HTTP_URL || 'http://localhost:8001').replace(/\/+$/, '');
}

export function decodeAreaClipState(value: unknown): AreaClipState {
  if (!value || typeof value !== 'object') {
    throw new AreaEventClipUnavailableError('Python worker returned an invalid clip response');
  }
  const candidate = value as Record<string, unknown>;
  const status = candidate.status;
  if (
    typeof candidate.violationId !== 'string'
    || typeof status !== 'string'
    || !CLIP_STATUSES.has(status as AreaClipStatus)
    || (candidate.clipUrl !== null && candidate.clipUrl !== undefined && typeof candidate.clipUrl !== 'string')
    || (candidate.message !== null && candidate.message !== undefined && typeof candidate.message !== 'string')
  ) {
    throw new AreaEventClipUnavailableError('Python worker returned an invalid clip response');
  }
  return {
    violationId: candidate.violationId,
    status: status as AreaClipStatus,
    clipUrl: typeof candidate.clipUrl === 'string' ? candidate.clipUrl : null,
    ...(typeof candidate.message === 'string' ? { message: candidate.message } : {}),
  };
}

async function callWorker(
  violationId: string,
  method: 'GET' | 'POST',
  fetchImpl: typeof fetch = fetch,
): Promise<AreaClipState> {
  const endpoint = `${getPythonWorkerHttpUrl()}/cameras/BAI-KIEM/violations/${encodeURIComponent(violationId)}/clip`;
  try {
    const response = await fetchImpl(endpoint, {
      method,
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      throw new AreaEventClipUnavailableError(
        `Python worker rejected clip request with HTTP ${response.status}`,
      );
    }
    return decodeAreaClipState(await response.json());
  } catch (error) {
    if (error instanceof AreaEventClipUnavailableError) throw error;
    throw new AreaEventClipUnavailableError('Python worker is unavailable for clip generation', {
      cause: error,
    });
  }
}

export function requestAreaEventClip(
  violationId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AreaClipState> {
  return callWorker(violationId, 'POST', fetchImpl);
}

export function getAreaEventClip(
  violationId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AreaClipState> {
  return callWorker(violationId, 'GET', fetchImpl);
}
