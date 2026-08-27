/**
 * routes/events.ts — Monitoring Events REST API Router (VS-GATE-LIVE, VS-AREA-VIOLATION)
 *
 * Implements querying and management for Gate Events and Area Violations (AP-02, AP-03, AP-04, M1, M2):
 * - GET  /api/v1/events/gate
 * - POST /api/v1/events/gate
 * - GET  /api/v1/events/area
 */
import fs from 'fs';
import path from 'path';
import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../prisma/client';
import {
  AreaEventResetUnavailableError,
  deleteAreaEventsViaWorker,
} from '../services/areaEventResetService';
import { BadRequestError } from '../utils/errors';
import { sendCreated, sendError, sendSuccess } from '../utils/response';
import { channelManager } from '../ws';

const eventsRouter = Router();

/**
 * Format timestamp to HH:mm for UI display
 */
function formatTime(d: Date): string {
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  return `${h}:${m}`;
}

/**
 * GET /api/v1/events/gate
 * Query params: limit, page, offset, status, plate, lane, camera_id
 */
eventsRouter.get('/gate', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const {
      limit = '50',
      page = '1',
      offset,
      status,
      plate,
      lane,
      camera_id = 'GATE-01',
    } = req.query;

    const limitNum = Math.max(1, Math.min(200, parseInt(String(limit), 10) || 50));
    const pageNum = Math.max(1, parseInt(String(page), 10) || 1);
    const skip = offset !== undefined ? Math.max(0, parseInt(String(offset), 10) || 0) : (pageNum - 1) * limitNum;

    const where: any = {};

    if (camera_id && String(camera_id).trim()) {
      where.cameraId = String(camera_id).trim();
    }

    if (status && String(status).toLowerCase() !== 'all') {
      const s = String(status).trim().toUpperCase();
      where.status = s === 'LA' || s === 'STRANGER' ? 'STRANGER' : 'KNOWN';
    }

    if (plate && String(plate).trim()) {
      const q = String(plate).trim().toUpperCase();
      where.licensePlate = { contains: q, mode: 'insensitive' };
    }

    if (lane && String(lane).trim()) {
      where.lane = String(lane).trim();
    }

    const [total, records] = await Promise.all([
      prisma.gateEvent.count({ where }),
      prisma.gateEvent.findMany({
        where,
        orderBy: { eventTimestamp: 'desc' },
        skip,
        take: limitNum,
      }),
    ]);

    const formatted = records.map((r) => {
      const isKnown = r.status === 'KNOWN';
      const confPercent = r.confidence ? Math.round(r.confidence * 100) : null;
      const laneLabel = r.lane === 'IN_2' ? 'Làn IN 2 · Làn phụ' : 'Làn IN 1 · Cổng chính';

      return {
        id: r.id,
        cameraId: r.cameraId,
        lane: r.lane,
        licensePlate: r.licensePlate,
        status: isKnown ? ('quen' as const) : ('la' as const),
        dbStatus: r.status,
        confidence: r.confidence,
        cropPath: r.cropPath,
        clipPath: r.clipPath,
        eventTimestamp: r.eventTimestamp.toISOString(),
        createdAt: r.createdAt.toISOString(),
        // UI helper properties
        time: formatTime(new Date(r.eventTimestamp)),
        plate: r.licensePlate,
        zone: laneLabel,
        conf: confPercent,
      };
    });

    return sendSuccess(res, formatted);
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /api/v1/events/gate
 * Ingestion endpoint for Python AI Worker or test simulators
 */
eventsRouter.post('/gate', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const {
      cameraId = 'GATE-01',
      lane = 'IN_1',
      licensePlate,
      plate,
      status = 'STRANGER',
      confidence = 0.95,
      cropPath,
      clipPath,
      timestamp,
    } = req.body;

    const rawPlate = licensePlate || plate;
    if (!rawPlate) {
      throw new BadRequestError('licensePlate is required');
    }

    const normalizedPlate = String(rawPlate).trim().toUpperCase();
    const isKnown = String(status).toUpperCase() === 'KNOWN' || String(status).toLowerCase() === 'quen';
    const canonicalStatus = isKnown ? 'KNOWN' : 'STRANGER';
    const confVal = Math.max(0.0, Math.min(1.0, parseFloat(confidence) || 0.95));
    const eventTime = timestamp ? new Date(timestamp) : new Date();

    const created = await prisma.gateEvent.create({
      data: {
        cameraId: String(cameraId),
        lane: String(lane),
        licensePlate: normalizedPlate,
        status: canonicalStatus,
        confidence: confVal,
        cropPath: cropPath ? String(cropPath) : null,
        clipPath: clipPath ? String(clipPath) : null,
        eventTimestamp: eventTime,
      },
    });

    const confPercent = Math.round(confVal * 100);
    const laneLabel = created.lane === 'IN_2' ? 'Làn IN 2 · Làn phụ' : 'Làn IN 1 · Cổng chính';

    const formatted = {
      id: created.id,
      cameraId: created.cameraId,
      lane: created.lane,
      licensePlate: created.licensePlate,
      status: isKnown ? ('quen' as const) : ('la' as const),
      dbStatus: created.status,
      confidence: created.confidence,
      cropPath: created.cropPath,
      clipPath: created.clipPath,
      eventTimestamp: created.eventTimestamp.toISOString(),
      createdAt: created.createdAt.toISOString(),
      time: formatTime(new Date(created.eventTimestamp)),
      plate: created.licensePlate,
      zone: laneLabel,
      conf: confPercent,
    };

    // Broadcast event to connected WebSocket clients via channelManager
    channelManager.broadcastGateEvent({
      type: 'gate_event',
      data: formatted,
    });

    return sendCreated(res, formatted);
  } catch (err) {
    return next(err);
  }
});

/**
 * GET /api/v1/events/area
 */
eventsRouter.get('/area', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { limit = '50', offset = '0', cameraId, zoneId } = req.query;
    const limitNum = Math.max(1, Math.min(200, parseInt(String(limit), 10) || 50));
    const skip = Math.max(0, parseInt(String(offset), 10) || 0);

    const where: any = {};
    if (cameraId) where.cameraId = String(cameraId);
    if (zoneId) where.zoneId = String(zoneId);

    const records = await prisma.zoneViolation.findMany({
      where,
      include: { zone: true },
      orderBy: { enteredAt: 'desc' },
      skip,
      take: limitNum,
    });

    const formatted = records.map((r) => ({
      id: r.id,
      time: formatTime(new Date(r.enteredAt)),
      obj: r.objectLabel,
      zone: r.zone ? r.zone.name : 'Khu vực bãi kiểm',
      st: r.status === 'OPEN' ? ('Vi phạm' as const) : ('Được phép' as const),
      ok: r.status !== 'OPEN',
      status: r.status,
      enteredAt: r.enteredAt.toISOString(),
      exitedAt: r.exitedAt?.toISOString() || null,
      durationSeconds: r.durationSeconds,
      clipPath: r.clipPath,
    }));

    return sendSuccess(res, formatted);
  } catch (err) {
    return next(err);
  }
});

/**
 * Resolve directory path for data subdirectories (clips, crops)
 */
function getMediaDirectory(subDir: string): string {
  const configuredDir = process.env[subDir.toUpperCase() + '_DIR'];
  const backendDir = path.resolve(__dirname, '../..');
  const configuredMediaDir = configuredDir
    ? path.isAbsolute(configuredDir)
      ? configuredDir
      : path.resolve(backendDir, configuredDir)
    : undefined;
  const candidates = [
    configuredMediaDir,
    path.resolve(__dirname, '../../data', subDir),
    path.resolve(__dirname, '../data', subDir),
    path.resolve(process.cwd(), '../data', subDir),
    path.resolve(process.cwd(), 'data', subDir),
  ].filter(Boolean) as string[];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  const fallback = path.resolve(backendDir, 'data', subDir);
  if (!fs.existsSync(fallback)) {
    try {
      fs.mkdirSync(fallback, { recursive: true });
    } catch {
      // ignore
    }
  }
  return fallback;
}

/**
 * Safely delete files matching a filter or all files in a directory (preserving .gitkeep)
 */
function cleanDirectoryFiles(dirPath: string, fileFilter?: (fileName: string) => boolean): number {
  let deletedCount = 0;
  try {
    if (!fs.existsSync(dirPath)) return 0;
    const files = fs.readdirSync(dirPath);
    for (const file of files) {
      if (file === '.gitkeep') continue;
      if (fileFilter && !fileFilter(file)) continue;
      const fullPath = path.join(dirPath, file);
      try {
        const stat = fs.statSync(fullPath);
        if (stat.isFile()) {
          fs.unlinkSync(fullPath);
          deletedCount++;
        }
      } catch {
        // ignore single file error
      }
    }
  } catch (err) {
    console.error(`Error cleaning directory ${dirPath}:`, err);
  }
  return deletedCount;
}

/**
 * DELETE /api/v1/events/area
 * Deletes all zone violation records from database and all area violation MP4 clips from disk.
 */
eventsRouter.delete('/area', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const deleteResult = await deleteAreaEventsViaWorker();
    const clipsDir = getMediaDirectory('clips');
    const deletedFiles = cleanDirectoryFiles(
      clipsDir,
      (file) => file.startsWith('area_') && file.endsWith('.mp4'),
    );

    return sendSuccess(res, {
      message: 'Đã xóa toàn bộ sự kiện khu vực và video clip 10s liên quan.',
      deletedRecords: deleteResult.deletedRecords,
      deletedFiles,
    });
  } catch (err) {
    if (err instanceof AreaEventResetUnavailableError) {
      return sendError(
        res,
        503,
        'AREA_RESET_UNAVAILABLE',
        'Không thể đồng bộ xóa sự kiện với Python Worker. Dữ liệu chưa bị xóa.',
      );
    }
    return next(err);
  }
});

/**
 * DELETE /api/v1/events/gate
 * Deletes all gate events from database and all license plate crops / gate clips from disk.
 */
eventsRouter.delete('/gate', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const deleteResult = await prisma.gateEvent.deleteMany({});
    const cropsDir = getMediaDirectory('crops');
    const clipsDir = getMediaDirectory('clips');

    const deletedCrops = cleanDirectoryFiles(cropsDir, (file) => file.startsWith('gate_crop_') || file.endsWith('.jpg') || file.endsWith('.png'));
    const deletedClips = cleanDirectoryFiles(clipsDir, (file) => file.startsWith('gate_clip_'));

    return sendSuccess(res, {
      message: 'Đã xóa toàn bộ sự kiện cổng và hình ảnh/video clip liên quan.',
      deletedRecords: deleteResult.count,
      deletedFiles: deletedCrops + deletedClips,
    });
  } catch (err) {
    return next(err);
  }
});

/**
 * DELETE /api/v1/events/all
 * Deletes all gate and area events from database and cleans up clips & crops folders.
 */
eventsRouter.delete('/all', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const areaResult = await deleteAreaEventsViaWorker();
    const gateResult = await prisma.gateEvent.deleteMany({});

    const clipsDir = getMediaDirectory('clips');
    const cropsDir = getMediaDirectory('crops');

    const deletedClips = cleanDirectoryFiles(clipsDir);
    const deletedCrops = cleanDirectoryFiles(cropsDir);

    return sendSuccess(res, {
      message: 'Đã xóa toàn bộ sự kiện và giải phóng toàn bộ video clip 10s, ảnh crop.',
      deletedAreaRecords: areaResult.deletedRecords,
      deletedGateRecords: gateResult.count,
      deletedFiles: deletedClips + deletedCrops,
    });
  } catch (err) {
    if (err instanceof AreaEventResetUnavailableError) {
      return sendError(
        res,
        503,
        'AREA_RESET_UNAVAILABLE',
        'Không thể đồng bộ xóa sự kiện với Python Worker. Dữ liệu chưa bị xóa.',
      );
    }
    return next(err);
  }
});

export { eventsRouter };

