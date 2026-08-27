export interface AreaEventResetResult {
  cameraId: 'BAI-KIEM';
  deletedRecords: number;
  clearedActive: number;
  clearedPending: number;
}

export class AreaEventResetUnavailableError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = 'AreaEventResetUnavailableError';
  }
}

function getPythonWorkerHttpUrl(): string {
  return (process.env.PYTHON_WORKER_HTTP_URL || 'http://localhost:8001').replace(/\/+$/, '');
}

function decodeResetResult(value: unknown): AreaEventResetResult {
  if (!value || typeof value !== 'object') {
    throw new AreaEventResetUnavailableError('Python worker returned an invalid Area reset response');
  }
  const candidate = value as Record<string, unknown>;
  if (
    candidate.cameraId !== 'BAI-KIEM'
    || typeof candidate.deletedRecords !== 'number'
    || !Number.isInteger(candidate.deletedRecords)
    || candidate.deletedRecords < 0
    || typeof candidate.clearedActive !== 'number'
    || !Number.isInteger(candidate.clearedActive)
    || candidate.clearedActive < 0
    || typeof candidate.clearedPending !== 'number'
    || !Number.isInteger(candidate.clearedPending)
    || candidate.clearedPending < 0
  ) {
    throw new AreaEventResetUnavailableError('Python worker returned an invalid Area reset response');
  }
  return {
    cameraId: 'BAI-KIEM',
    deletedRecords: candidate.deletedRecords,
    clearedActive: candidate.clearedActive,
    clearedPending: candidate.clearedPending,
  };
}

export async function deleteAreaEventsViaWorker(
  fetchImpl: typeof fetch = fetch,
): Promise<AreaEventResetResult> {
  const endpoint = `${getPythonWorkerHttpUrl()}/cameras/BAI-KIEM/violations`;
  try {
    const response = await fetchImpl(endpoint, {
      method: 'DELETE',
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      throw new AreaEventResetUnavailableError(
        `Python worker rejected Area reset with HTTP ${response.status}`,
      );
    }
    return decodeResetResult(await response.json());
  } catch (error) {
    if (error instanceof AreaEventResetUnavailableError) {
      throw error;
    }
    throw new AreaEventResetUnavailableError(
      'Python worker is unavailable; Area events were not deleted',
      { cause: error },
    );
  }
}
