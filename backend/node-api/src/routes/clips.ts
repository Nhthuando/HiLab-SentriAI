import path from 'path';
import { Router, type Request, type Response } from 'express';
import { findEventClipRecord, resolveStoredClipPath } from '../services/clipService';
import { sendError } from '../utils/response';

const clipsRouter = Router();
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function resolveRequestedClip(req: Request, res: Response): Promise<string | null> {
  const eventId = req.params.id;
  if (!UUID_PATTERN.test(eventId)) {
    sendError(res, 400, 'VALIDATION_ERROR', 'Clip id must be an event UUID');
    return null;
  }
  const record = await findEventClipRecord(eventId);
  if (!record) {
    sendError(res, 404, 'NOT_FOUND', 'Event not found');
    return null;
  }
  const filePath = resolveStoredClipPath(record.clipPath);
  if (!filePath) {
    sendError(res, 404, 'CLIP_NOT_AVAILABLE', 'Không có clip');
    return null;
  }
  return filePath;
}

clipsRouter.get('/:id/stream', async (req: Request, res: Response) => {
  try {
    const filePath = await resolveRequestedClip(req, res);
    if (!filePath) return;
    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Accept-Ranges', 'bytes');
    res.setHeader('Cache-Control', 'private, max-age=60');
    res.sendFile(filePath);
  } catch (error) {
    console.error('[clipsRouter] Failed to stream clip:', error);
    if (!res.headersSent) sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to stream clip');
  }
});

clipsRouter.get('/:id/download', async (req: Request, res: Response) => {
  try {
    const filePath = await resolveRequestedClip(req, res);
    if (!filePath) return;
    res.download(filePath, path.basename(filePath));
  } catch (error) {
    console.error('[clipsRouter] Failed to download clip:', error);
    if (!res.headersSent) sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to download clip');
  }
});

export { clipsRouter };

