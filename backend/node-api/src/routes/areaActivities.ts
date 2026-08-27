import type { Prisma } from '@prisma/client';
import { Router, type Request, type Response } from 'express';
import { prisma } from '../prisma/client';
import {
  getAreaActivityClip,
  requestAreaActivityClip,
} from '../services/areaActivityClipService';
import { AreaEventClipUnavailableError } from '../services/areaEventClipService';
import { sendError, sendSuccess } from '../utils/response';

const router = Router();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function single(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function invalid(value: unknown): boolean {
  return Array.isArray(value) || (value !== undefined && typeof value !== 'string');
}

function bounded(value: string | undefined, fallback: number, min: number, max: number): number | null {
  if (value === undefined) return fallback;
  if (!/^(0|[1-9]\d*)$/.test(value)) return null;
  const parsed = Number(value);
  return parsed >= min && parsed <= max ? parsed : null;
}

router.get('/', async (req: Request, res: Response) => {
  const values = [req.query.limit, req.query.offset, req.query.zone_id, req.query.object_label,
    req.query.canonical_class, req.query.policy_result, req.query.session_status, req.query.start, req.query.end];
  if (values.some(invalid)) return sendError(res, 400, 'VALIDATION_ERROR', 'Query parameters must be single string values');
  const limit = bounded(single(req.query.limit), 50, 1, 100);
  const offset = bounded(single(req.query.offset), 0, 0, Number.MAX_SAFE_INTEGER);
  if (limit === null || offset === null) return sendError(res, 400, 'VALIDATION_ERROR', 'Invalid pagination');
  const zoneId = single(req.query.zone_id);
  const policyResult = single(req.query.policy_result);
  const sessionStatus = single(req.query.session_status);
  if (zoneId && !UUID.test(zoneId)) return sendError(res, 400, 'VALIDATION_ERROR', 'zone_id must be a UUID');
  if (policyResult && !['ALLOWED', 'VIOLATION'].includes(policyResult)) return sendError(res, 400, 'VALIDATION_ERROR', 'Invalid policy_result');
  if (sessionStatus && !['OPEN', 'CLOSED'].includes(sessionStatus)) return sendError(res, 400, 'VALIDATION_ERROR', 'Invalid session_status');
  const start = single(req.query.start) ? new Date(single(req.query.start)!) : undefined;
  const end = single(req.query.end) ? new Date(single(req.query.end)!) : undefined;
  if ((start && Number.isNaN(start.getTime())) || (end && Number.isNaN(end.getTime())) || (start && end && start >= end)) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'Invalid date range');
  }

  const where: Prisma.AreaActivitySessionWhereInput = {
    cameraId: 'BAI-KIEM',
    ...(zoneId ? { zoneId } : {}),
    ...(single(req.query.object_label) ? { objectLabel: { contains: single(req.query.object_label)!, mode: 'insensitive' } } : {}),
    ...(single(req.query.canonical_class) ? { canonicalClass: { equals: single(req.query.canonical_class)!, mode: 'insensitive' } } : {}),
    ...(policyResult ? { policyResult } : {}),
    ...(sessionStatus ? { sessionStatus } : {}),
    ...(start || end ? { enteredAt: { ...(start ? { gte: start } : {}), ...(end ? { lt: end } : {}) } } : {}),
  };
  try {
    const [total, items] = await Promise.all([
      prisma.areaActivitySession.count({ where }),
      prisma.areaActivitySession.findMany({ where, orderBy: [{ enteredAt: 'desc' }, { id: 'desc' }], take: limit, skip: offset }),
    ]);
    return sendSuccess(res, { items, total, limit, offset });
  } catch (error) {
    console.error('[areaActivities] Failed to list activity:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to retrieve Area activity');
  }
});

for (const method of ['get', 'post'] as const) {
  router[method]('/:id/clip', async (req: Request, res: Response) => {
    const activityId = req.params.id;
    if (!UUID.test(activityId)) return sendError(res, 400, 'VALIDATION_ERROR', 'Activity id must be a UUID');
    try {
      const exists = await prisma.areaActivitySession.findFirst({ where: { id: activityId, cameraId: 'BAI-KIEM' }, select: { id: true } });
      if (!exists) return sendError(res, 404, 'NOT_FOUND', 'Area activity not found');
      const state = method === 'post'
        ? await requestAreaActivityClip(activityId)
        : await getAreaActivityClip(activityId);
      return sendSuccess(res, state, method === 'post' && state.status === 'QUEUED' ? 202 : 200);
    } catch (error) {
      if (error instanceof AreaEventClipUnavailableError) {
        return sendError(res, 503, 'AREA_ACTIVITY_CLIP_UNAVAILABLE', 'Không thể xử lý video hoạt động lúc này. Hãy thử lại.');
      }
      console.error('[areaActivities] Activity clip failure:', error);
      return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to process Area activity clip');
    }
  });
}

export { router as areaActivitiesRouter };
