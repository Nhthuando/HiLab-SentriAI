/**
 * routes/vehicles.ts — Registered Vehicles Management REST API Router (VS-SETTINGS-VEHICLE)
 *
 * Implements CRUD and status toggling for registered vehicles (AP-01, M1, M3):
 * - GET    /api/v1/vehicles
 * - POST   /api/v1/vehicles
 * - PATCH  /api/v1/vehicles/:id
 * - PATCH  /api/v1/vehicles/:idOrPlate/status
 * - DELETE /api/v1/vehicles/:id
 */
import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../prisma/client';
import { BadRequestError, ConflictError, NotFoundError } from '../utils/errors';
import { sendCreated, sendNoContent, sendSuccess } from '../utils/response';

const vehiclesRouter = Router();

/**
 * Normalize vehicle plate number to uppercase with clean spacing.
 * e.g. " 15r - 158.45 " -> "15R-158.45"
 */
export function normalizePlate(raw: string): string {
  if (!raw) return '';
  return raw
    .trim()
    .toUpperCase()
    .replace(/\s+/g, '');
}

/**
 * Map status strings between frontend ('quen' | 'la') and DB ('KNOWN' | 'STRANGER')
 */
export function normalizeStatus(status?: string): 'KNOWN' | 'STRANGER' {
  if (!status) return 'KNOWN';
  const s = status.trim().toUpperCase();
  if (s === 'LA' || s === 'STRANGER') return 'STRANGER';
  return 'KNOWN';
}

/**
 * GET /api/v1/vehicles
 * Query params: status, search, type, page, limit
 */
vehiclesRouter.get('/', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { status, search, page = '1', limit = '50' } = req.query;
    const pageNum = Math.max(1, parseInt(String(page), 10) || 1);
    const limitNum = Math.max(1, Math.min(200, parseInt(String(limit), 10) || 50));
    const skip = (pageNum - 1) * limitNum;

    const where: any = {};

    if (status && String(status).toLowerCase() !== 'all') {
      where.status = normalizeStatus(String(status));
    }

    if (search && String(search).trim()) {
      const q = normalizePlate(String(search));
      const rawQ = String(search).trim();
      where.OR = [
        { plateNumber: { contains: q, mode: 'insensitive' } },
        { plateNumber: { contains: rawQ, mode: 'insensitive' } },
        { note: { contains: rawQ, mode: 'insensitive' } },
      ];
    }

    const [total, records] = await Promise.all([
      prisma.registeredVehicle.count({ where }),
      prisma.registeredVehicle.findMany({
        where,
        orderBy: { updatedAt: 'desc' },
        skip,
        take: limitNum,
      }),
    ]);

    // Query gate event stats for each plate to provide visits and last seen
    const plates = records.map((r) => r.plateNumber);
    const gateStats = await prisma.gateEvent.groupBy({
      by: ['licensePlate'],
      where: { licensePlate: { in: plates } },
      _count: { id: true },
      _max: { eventTimestamp: true },
    });

    const statsMap = new Map<string, { count: number; maxTimestamp: Date | null }>();
    for (const stat of gateStats) {
      statsMap.set(stat.licensePlate, {
        count: stat._count.id,
        maxTimestamp: stat._max.eventTimestamp,
      });
    }

    // Format output with both database record and UI helper fields
    const formatted = records.map((r) => {
      const stat = statsMap.get(r.plateNumber);
      const visits = stat ? stat.count : 1;
      const lastDate = stat?.maxTimestamp || r.updatedAt;
      const formattedLast = new Intl.DateTimeFormat('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(new Date(lastDate));

      const isContainer = r.plateNumber.includes('R') || r.plateNumber.includes('H');
      const isTruck = r.plateNumber.includes('C');
      const inferredType = isContainer ? 'Container' : isTruck ? 'Xe tải' : 'Xe con';

      return {
        id: r.id,
        plateNumber: r.plateNumber,
        status: r.status,
        note: r.note,
        createdAt: r.createdAt.toISOString(),
        updatedAt: r.updatedAt.toISOString(),
        // UI helper properties for seamless frontend integration
        plate: r.plateNumber,
        type: inferredType,
        visits,
        last: formattedLast,
        tint: r.status === 'KNOWN' ? '#10b981' : '#f43f5e',
      };
    });

    return sendSuccess(res, formatted);
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /api/v1/vehicles
 * Body: { plateNumber, status, note }
 */
vehiclesRouter.post('/', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const rawPlate = req.body.plateNumber || req.body.plate_number || req.body.plate;
    if (!rawPlate || typeof rawPlate !== 'string') {
      throw new BadRequestError('plateNumber is required and must be a string');
    }

    const plateNumber = normalizePlate(rawPlate);
    if (plateNumber.length === 0 || plateNumber.length > 20) {
      throw new BadRequestError('plateNumber must be between 1 and 20 characters');
    }

    const status = normalizeStatus(req.body.status);
    const note = req.body.note ? String(req.body.note).trim() : null;

    // Check if plate already exists
    const existing = await prisma.registeredVehicle.findUnique({
      where: { plateNumber },
    });

    if (existing) {
      throw new ConflictError(`Biển số xe '${plateNumber}' đã tồn tại trong danh mục.`);
    }

    const created = await prisma.registeredVehicle.create({
      data: {
        plateNumber,
        status,
        note,
      },
    });

    return sendCreated(res, created);
  } catch (err) {
    return next(err);
  }
});

/**
 * PATCH /api/v1/vehicles/:idOrPlate/status
 * or PATCH /api/v1/vehicles/:id
 * Body: { status, note }
 */
const handleUpdate = async (req: Request, res: Response, next: NextFunction) => {
  try {
    const param = req.params.id || req.params.plate || req.params.idOrPlate;
    if (!param) {
      throw new BadRequestError('Vehicle identifier is required');
    }

    // Check if param is UUID or plate number
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(param);
    const cleanPlate = normalizePlate(param);

    const existing = await prisma.registeredVehicle.findFirst({
      where: isUuid
        ? { id: param }
        : {
            OR: [
              { plateNumber: cleanPlate },
              { plateNumber: param.trim().toUpperCase() },
            ],
          },
    });

    if (!existing) {
      throw new NotFoundError(`Không tìm thấy phương tiện với định danh '${param}'`);
    }

    const dataToUpdate: any = {};
    if (req.body.status !== undefined) {
      dataToUpdate.status = normalizeStatus(req.body.status);
    }
    if (req.body.note !== undefined) {
      dataToUpdate.note = req.body.note ? String(req.body.note).trim() : null;
    }

    const updated = await prisma.registeredVehicle.update({
      where: { id: existing.id },
      data: dataToUpdate,
    });

    const isContainer = updated.plateNumber.includes('R') || updated.plateNumber.includes('H');
    const isTruck = updated.plateNumber.includes('C');
    const inferredType = isContainer ? 'Container' : isTruck ? 'Xe tải' : 'Xe con';

    const formatted = {
      id: updated.id,
      plateNumber: updated.plateNumber,
      status: updated.status,
      note: updated.note,
      createdAt: updated.createdAt.toISOString(),
      updatedAt: updated.updatedAt.toISOString(),
      plate: updated.plateNumber,
      type: inferredType,
      visits: 1,
      last: 'Vừa xong',
      tint: updated.status === 'KNOWN' ? '#10b981' : '#f43f5e',
    };

    return sendSuccess(res, formatted);
  } catch (err) {
    return next(err);
  }
};

vehiclesRouter.patch('/:id/status', handleUpdate);
vehiclesRouter.patch('/:plate/label', handleUpdate);
vehiclesRouter.patch('/:id', handleUpdate);

/**
 * DELETE /api/v1/vehicles/:id
 */
vehiclesRouter.delete('/:id', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const param = req.params.id;
    if (!param) {
      throw new BadRequestError('Vehicle identifier is required');
    }

    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(param);
    const cleanPlate = normalizePlate(param);

    const existing = await prisma.registeredVehicle.findFirst({
      where: isUuid
        ? { id: param }
        : {
            OR: [
              { plateNumber: cleanPlate },
              { plateNumber: param.trim().toUpperCase() },
            ],
          },
    });

    if (!existing) {
      throw new NotFoundError(`Không tìm thấy phương tiện với định danh '${param}'`);
    }

    await prisma.registeredVehicle.delete({
      where: { id: existing.id },
    });

    return sendNoContent(res);
  } catch (err) {
    return next(err);
  }
});

export { vehiclesRouter };
