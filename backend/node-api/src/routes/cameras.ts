import { Request, Response, Router } from 'express';
import { sendError, sendSuccess } from '../utils/response';

const camerasRouter = Router();

function getPythonWorkerHttpUrl(): string {
  return (process.env.PYTHON_WORKER_HTTP_URL || 'http://localhost:8001').replace(/\/+$/, '');
}

const SUPPORTED_CAMERAS = new Set(['BAI-KIEM', 'GATE-01']);

function normalizeCameraId(raw: string): string {
  const upper = raw.trim().toUpperCase();
  if (['GATE', 'GATE1', 'GATE_01', 'GATE-01'].includes(upper)) return 'GATE-01';
  if (['AREA', 'BAIKIEM', 'BAI_KIEM', 'BAI-KIEM'].includes(upper)) return 'BAI-KIEM';
  return upper;
}

function validatedCameraId(req: Request, res: Response): string | null {
  const cameraId = normalizeCameraId(req.params.id);
  if (!SUPPORTED_CAMERAS.has(cameraId)) {
    sendError(res, 400, 'VALIDATION_ERROR', `Camera '${req.params.id}' is not supported. Valid cameras: BAI-KIEM, GATE-01`);
    return null;
  }
  return cameraId;
}

camerasRouter.get('/:id/snapshot', async (req: Request, res: Response) => {
  const cameraId = validatedCameraId(req, res);
  if (!cameraId) return;

  try {
    const upstream = await fetch(
      `${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/snapshot`,
      { signal: AbortSignal.timeout(5000) },
    );
    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' is unavailable`);
    }
    const contentType = upstream.headers.get('content-type') || '';
    if (!contentType.startsWith('image/')) {
      return sendError(res, 502, 'CAMERA_SNAPSHOT_INVALID', 'Camera returned an invalid snapshot');
    }
    const image = Buffer.from(await upstream.arrayBuffer()).toString('base64');
    return sendSuccess(res, { image: `data:${contentType};base64,${image}` });
  } catch (error) {
    console.error(`[camerasRouter] Failed to load snapshot for ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' is unavailable`);
  }
});

camerasRouter.get('/:id/playback', async (req: Request, res: Response) => {
  const cameraId = validatedCameraId(req, res);
  if (!cameraId) return;

  try {
    const upstream = await fetch(
      `${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/playback`,
      { signal: AbortSignal.timeout(5000) },
    );
    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' playback is unavailable`);
    }
    return sendSuccess(res, await upstream.json());
  } catch (error) {
    console.error(`[camerasRouter] Failed to load playback for ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' playback is unavailable`);
  }
});

camerasRouter.get('/:id/playback/preview', async (req: Request, res: Response) => {
  const cameraId = validatedCameraId(req, res);
  const positionSeconds = Number(req.query.positionSeconds);
  if (!cameraId) return;
  if (!Number.isFinite(positionSeconds) || positionSeconds < 0) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'A non-negative positionSeconds is required');
  }

  try {
    const upstream = await fetch(
      `${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/playback/preview?positionSeconds=${encodeURIComponent(String(positionSeconds))}`,
      { signal: AbortSignal.timeout(5000) },
    );
    if (!upstream.ok) {
      return sendError(res, upstream.status === 409 ? 409 : 503, 'CAMERA_PREVIEW_UNAVAILABLE', `Camera '${cameraId}' cannot provide a seek preview`);
    }
    const contentType = upstream.headers.get('content-type') || '';
    if (!contentType.startsWith('image/')) {
      return sendError(res, 502, 'CAMERA_PREVIEW_INVALID', 'Camera returned an invalid seek preview');
    }
    const image = Buffer.from(await upstream.arrayBuffer()).toString('base64');
    return sendSuccess(res, { image: `data:${contentType};base64,${image}` });
  } catch (error) {
    console.error(`[camerasRouter] Failed to preview ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_PREVIEW_UNAVAILABLE', `Camera '${cameraId}' cannot provide a seek preview`);
  }
});

camerasRouter.post('/:id/playback', async (req: Request, res: Response) => {
  const cameraId = validatedCameraId(req, res);
  const positionSeconds = Number(req.body?.positionSeconds);
  if (!cameraId) return;
  if (!Number.isFinite(positionSeconds) || positionSeconds < 0) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'A non-negative positionSeconds is required');
  }

  try {
    const upstream = await fetch(
      `${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/playback`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ positionSeconds }),
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' cannot seek`);
    }
    return sendSuccess(res, await upstream.json());
  } catch (error) {
    console.error(`[camerasRouter] Failed to seek ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' cannot seek`);
  }
});

camerasRouter.post('/:id/seek', async (req: Request, res: Response) => {
  const cameraId = validatedCameraId(req, res);
  const positionMs = Number(req.body?.positionMs);
  if (!cameraId) return;
  if (!Number.isFinite(positionMs) || positionMs < 0) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'A non-negative positionMs is required');
  }

  try {
    const upstream = await fetch(
      `${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/seek`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ positionMs }),
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' seek is unavailable`);
    }
    return sendSuccess(res, await upstream.json());
  } catch (error) {
    console.error(`[camerasRouter] Failed to seek ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' seek is unavailable`);
  }
});

camerasRouter.get('/:id/config', async (req: Request, res: Response) => {
  const cameraId = validatedCameraId(req, res);
  if (!cameraId) return;

  try {
    const upstream = await fetch(
      `${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/config`,
      { signal: AbortSignal.timeout(5000) },
    );
    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' config is unavailable`);
    }
    return sendSuccess(res, await upstream.json());
  } catch (error) {
    console.error(`[camerasRouter] Failed to load config for ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' config is unavailable`);
  }
});

camerasRouter.post('/:id/config', async (req: Request, res: Response) => {
  const cameraId = validatedCameraId(req, res);
  if (!cameraId) return;

  try {
    const upstream = await fetch(
      `${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/config`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body || {}),
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' config update is unavailable`);
    }
    return sendSuccess(res, await upstream.json());
  } catch (error) {
    console.error(`[camerasRouter] Failed to update config for ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' config update is unavailable`);
  }
});

export { camerasRouter };
