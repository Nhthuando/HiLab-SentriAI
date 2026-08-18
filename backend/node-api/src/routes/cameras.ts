import { Request, Response, Router } from 'express';
import { sendError, sendSuccess } from '../utils/response';
import { AREA_CAMERA_ID } from './zones';

const camerasRouter = Router();

function getPythonWorkerHttpUrl(): string {
  return (process.env.PYTHON_WORKER_HTTP_URL || 'http://localhost:8001').replace(/\/+$/, '');
}

camerasRouter.get('/:id/snapshot', async (req: Request, res: Response) => {
  const cameraId = req.params.id.trim().toUpperCase();
  if (cameraId !== AREA_CAMERA_ID) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'Only BAI-KIEM snapshots are supported');
  }

  try {
    const upstream = await fetch(
      `${getPythonWorkerHttpUrl()}/cameras/${encodeURIComponent(AREA_CAMERA_ID)}/snapshot`,
      { signal: AbortSignal.timeout(5000) },
    );

    if (!upstream.ok) {
      return sendError(res, 503, 'CAMERA_UNAVAILABLE', 'BAI-KIEM camera is unavailable');
    }

    const contentType = upstream.headers.get('content-type') || '';
    if (!contentType.startsWith('image/')) {
      return sendError(res, 502, 'CAMERA_SNAPSHOT_INVALID', 'Camera returned an invalid snapshot');
    }

    const image = Buffer.from(await upstream.arrayBuffer()).toString('base64');
    return sendSuccess(res, { image: `data:${contentType};base64,${image}` });
  } catch (error) {
    console.error('[camerasRouter] Failed to load BAI-KIEM snapshot:', error);
    return sendError(res, 503, 'CAMERA_UNAVAILABLE', 'BAI-KIEM camera is unavailable');
  }
});

export { camerasRouter };
