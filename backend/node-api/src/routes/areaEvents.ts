/**
 * routes/areaEvents.ts — Area Monitoring Zone Violations REST Route (VS-AREA-VIOLATION)
 *
 * Implements GET /api/v1/events/area with pagination, filtering by zone_id and status,
 * and standard API envelope response.
 */
import { Request, Response, Router } from 'express';
import type { Prisma } from '@prisma/client';
import { prisma } from '../prisma/client';
import {
  AreaEventClipUnavailableError,
  type AreaClipState,
  type AreaClipStatus,
  requestAreaEventClip,
} from '../services/areaEventClipService';
import { sendError, sendSuccess } from '../utils/response';

const areaEventsRouter = Router();
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function getSingleQueryValue(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function isInvalidQueryValue(value: unknown): boolean {
  return Array.isArray(value) || (value !== undefined && typeof value !== 'string');
}

function parseBoundedInteger(
  value: string | undefined,
  defaultValue: number,
  min: number,
  max: number,
): number | null {
  if (value === undefined) return defaultValue;
  if (!/^(0|[1-9]\d*)$/.test(value)) return null;

  const parsed = Number(value);
  return parsed >= min && parsed <= max ? parsed : null;
}

export interface AreaViolationDto {
  id: string;
  cameraId: string;
  zoneId: string;
  zoneName: string;
  objectLabel: string;
  status: 'OPEN' | 'CLOSED' | string;
  enteredAt: string;
  exitedAt: string | null;
  durationSeconds: number | null;
  clipStatus: AreaClipStatus;
  clipAvailable: boolean;
  clipUrl: string | null;
}

export interface AreaEventsResponseData {
  items: AreaViolationDto[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * GET /api/v1/events/area
 * Query zone violations with pagination, optional zone_id and status filters.
 */
areaEventsRouter.get('/', async (req: Request, res: Response) => {
  try {
    const queryValues = [req.query.limit, req.query.offset, req.query.zone_id, req.query.status];
    if (queryValues.some(isInvalidQueryValue)) {
      return sendError(res, 400, 'VALIDATION_ERROR', 'Query parameters must be single string values');
    }

    const rawLimit = parseBoundedInteger(getSingleQueryValue(req.query.limit), 50, 1, 100);
    const rawOffset = parseBoundedInteger(getSingleQueryValue(req.query.offset), 0, 0, Number.MAX_SAFE_INTEGER);
    const zoneId = getSingleQueryValue(req.query.zone_id);
    const status = getSingleQueryValue(req.query.status);

    if (rawLimit === null) {
      return sendError(res, 400, 'VALIDATION_ERROR', 'Limit must be an integer between 1 and 100');
    }

    if (rawOffset === null) {
      return sendError(res, 400, 'VALIDATION_ERROR', 'Offset must be a non-negative integer');
    }

    if (status !== undefined && status !== 'OPEN' && status !== 'CLOSED') {
      return sendError(res, 400, 'VALIDATION_ERROR', "Status must be 'OPEN' or 'CLOSED'");
    }

    if (zoneId !== undefined && !UUID_PATTERN.test(zoneId)) {
      return sendError(res, 400, 'VALIDATION_ERROR', 'zone_id must be a UUID');
    }

    const where: Prisma.ZoneViolationWhereInput = {
      cameraId: 'BAI-KIEM',
    };
    if (zoneId) {
      where.zoneId = zoneId;
    }
    if (status) {
      where.status = status;
    }

    // Query count and paginated items in parallel
    const [total, rows] = await Promise.all([
      prisma.zoneViolation.count({ where }),
      prisma.zoneViolation.findMany({
        where,
        include: {
          zone: {
            select: {
              name: true,
            },
          },
        },
        orderBy: [
          { enteredAt: 'desc' },
          { id: 'desc' },
        ],
        take: rawLimit,
        skip: rawOffset,
      }),
    ]);

    const items: AreaViolationDto[] = rows.map((r) => {
      const clipStatus = (r.clipStatus || (r.clipPath ? 'READY' : 'NOT_REQUESTED')) as AreaClipStatus;
      let clipUrl: string | null = null;
      if (clipStatus === 'READY' && r.clipPath) {
        const cleanName = r.clipPath.replace(/^.*[\\/]/, '');
        clipUrl = `/data/clips/${encodeURIComponent(cleanName)}`;
      }

      return {
        id: r.id,
        cameraId: r.cameraId,
        zoneId: r.zoneId,
        zoneName: r.zone?.name ?? 'Khu vực giám sát',
        objectLabel: r.objectLabel,
        status: r.status,
        enteredAt: r.enteredAt.toISOString(),
        exitedAt: r.exitedAt ? r.exitedAt.toISOString() : null,
        durationSeconds: r.durationSeconds,
        clipStatus,
        clipAvailable: clipStatus === 'READY' && Boolean(clipUrl),
        clipUrl,
      };
    });

    const data: AreaEventsResponseData = {
      items,
      total,
      limit: rawLimit,
      offset: rawOffset,
    };

    return sendSuccess(res, data);
  } catch (err) {
    console.error('[areaEventsRouter] Error fetching area events:', err);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to retrieve area violation events');
  }
});

function clipStateFromRecord(record: {
  id: string;
  clipStatus: string;
  clipPath: string | null;
  clipError: string | null;
}): AreaClipState {
  const status = (record.clipStatus || (record.clipPath ? 'READY' : 'NOT_REQUESTED')) as AreaClipStatus;
  const cleanName = status === 'READY' && record.clipPath
    ? record.clipPath.replace(/^.*[\\/]/, '')
    : null;
  return {
    violationId: record.id,
    status,
    clipUrl: cleanName ? `/data/clips/${encodeURIComponent(cleanName)}` : null,
    ...(record.clipError ? { message: record.clipError } : {}),
  };
}

areaEventsRouter.post('/:id/clip', async (req: Request, res: Response) => {
  const violationId = req.params.id;
  if (!UUID_PATTERN.test(violationId)) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'Event id must be a UUID');
  }
  try {
    const exists = await prisma.zoneViolation.findFirst({
      where: { id: violationId, cameraId: 'BAI-KIEM' },
      select: { id: true },
    });
    if (!exists) {
      return sendError(res, 404, 'NOT_FOUND', 'Area violation event not found');
    }
    const state = await requestAreaEventClip(violationId);
    return sendSuccess(res, state, state.status === 'QUEUED' ? 202 : 200);
  } catch (error) {
    if (error instanceof AreaEventClipUnavailableError) {
      return sendError(
        res,
        503,
        'AREA_CLIP_UNAVAILABLE',
        'Không thể bắt đầu tạo video lúc này. Hãy thử lại.',
      );
    }
    console.error('[areaEventsRouter] Error requesting Area clip:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to request Area event clip');
  }
});

areaEventsRouter.get('/:id/clip', async (req: Request, res: Response) => {
  const violationId = req.params.id;
  if (!UUID_PATTERN.test(violationId)) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'Event id must be a UUID');
  }
  try {
    const record = await prisma.zoneViolation.findFirst({
      where: { id: violationId, cameraId: 'BAI-KIEM' },
      select: {
        id: true,
        clipStatus: true,
        clipPath: true,
        clipError: true,
      },
    });
    if (!record) {
      return sendError(res, 404, 'NOT_FOUND', 'Area violation event not found');
    }
    return sendSuccess(res, clipStateFromRecord(record));
  } catch (error) {
    console.error('[areaEventsRouter] Error reading Area clip status:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to read Area event clip status');
  }
});

export { areaEventsRouter };
