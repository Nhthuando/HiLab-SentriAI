import { Request, Response, Router } from 'express';
import { sendError, sendSuccess } from '../utils/response';
import { AREA_CAMERA_ID } from './zones';

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

camerasRouter.get('/:id/snapshot', async (req: Request, res: Response) => {
  const cameraId = normalizeCameraId(req.params.id);
  if (!SUPPORTED_CAMERAS.has(cameraId)) {
    return sendError(res, 400, 'VALIDATION_ERROR', `Camera '${req.params.id}' is not supported. Valid cameras: BAI-KIEM, GATE-01`);
  }

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
  const cameraId = normalizeCameraId(req.params.id);
  if (!SUPPORTED_CAMERAS.has(cameraId)) {
    return sendError(res, 400, 'VALIDATION_ERROR', `Camera '${req.params.id}' is not supported. Valid cameras: BAI-KIEM, GATE-01`);
  }

  try {
    const upstream = await fetch(`${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/playback`);
    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' playback is unavailable`);
    }
    return sendSuccess(res, await upstream.json());
  } catch (error) {
    console.error(`[camerasRouter] Failed to load playback for ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' playback is unavailable`);
  }
});

camerasRouter.post('/:id/seek', async (req: Request, res: Response) => {
  const cameraId = normalizeCameraId(req.params.id);
  if (!SUPPORTED_CAMERAS.has(cameraId)) {
    return sendError(res, 400, 'VALIDATION_ERROR', `Camera '${req.params.id}' is not supported. Valid cameras: BAI-KIEM, GATE-01`);
  }

  try {
    const upstream = await fetch(`${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(cameraId)}/seek`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positionMs: Number(req.body?.positionMs || 0) }),
    });
    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' seek is unavailable`);
    }
    return sendSuccess(res, await upstream.json());
  } catch (error) {
    console.error(`[camerasRouter] Failed to seek ${cameraId}:`, error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', `Camera '${cameraId}' seek is unavailable`);
  }
});

export { camerasRouter };
