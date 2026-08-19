/**
 * routes/labels.ts — Object Labels Management REST API Router (VS-SETTINGS-LABEL)
 *
 * Implements CRUD for Object Labels category mapping (M3, AC-06):
 * - GET    /api/v1/labels
 * - POST   /api/v1/labels
 * - PUT    /api/v1/labels/:id
 * - DELETE /api/v1/labels/:id
 * - GET    /api/v1/labels/:id/samples
 */
import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../prisma/client';
import { BadRequestError, ConflictError, NotFoundError } from '../utils/errors';
import { sendCreated, sendNoContent, sendSuccess } from '../utils/response';

const labelsRouter = Router();

const DEFAULT_TINTS = [
  '#3b82f6', // Classic Blue
  '#10b981', // Emerald
  '#06b6d4', // Cyan
  '#a855f7', // Purple
  '#f59e0b', // Amber
  '#f43f5e', // Rose
  '#8b5cf6', // Violet
  '#64748b', // Slate
];

/**
 * Infer kind ('xe' | 'nguoi') from baseClass or Vietnamese name
 */
function inferKind(baseClass: string, name: string): 'xe' | 'nguoi' {
  const s = `${baseClass} ${name}`.toLowerCase();
  if (s.includes('người') || s.includes('person') || s.includes('worker') || s.includes('walker')) {
    return 'nguoi';
  }
  return 'xe';
}

/**
 * GET /api/v1/labels
 * Returns all labels with sample count and UI formatting.
 */
labelsRouter.get('/', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const records = await prisma.objectLabel.findMany({
      include: {
        _count: {
          select: { samples: true },
        },
      },
      orderBy: { vietnameseName: 'asc' },
    });

    const formatted = records.map((r, index) => {
      const kind = inferKind(r.baseClass, r.vietnameseName);
      const tint = DEFAULT_TINTS[index % DEFAULT_TINTS.length];

      return {
        id: r.id,
        vietnameseName: r.vietnameseName,
        baseClass: r.baseClass,
        createdAt: r.createdAt.toISOString(),
        updatedAt: r.updatedAt.toISOString(),
        // UI helper properties
        name: r.vietnameseName,
        kind,
        tint,
        samples: r._count.samples,
      };
    });

    return sendSuccess(res, formatted);
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /api/v1/labels
 * Body: { vietnameseName, baseClass, kind?, tint? }
 */
labelsRouter.post('/', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const rawName = req.body.vietnameseName || req.body.name;
    const rawBaseClass = req.body.baseClass || (req.body.kind === 'nguoi' ? 'person' : 'car');

    if (!rawName || typeof rawName !== 'string' || !rawName.trim()) {
      throw new BadRequestError('vietnameseName is required');
    }

    const vietnameseName = rawName.trim();
    const baseClass = String(rawBaseClass).trim();

    // Check unique vietnameseName
    const existing = await prisma.objectLabel.findUnique({
      where: { vietnameseName },
    });

    if (existing) {
      throw new ConflictError(`Nhãn '${vietnameseName}' đã tồn tại trong danh mục.`);
    }

    const created = await prisma.objectLabel.create({
      data: {
        vietnameseName,
        baseClass,
      },
    });

    const kind = inferKind(created.baseClass, created.vietnameseName);
    const tint = req.body.tint || DEFAULT_TINTS[0];

    const formatted = {
      id: created.id,
      vietnameseName: created.vietnameseName,
      baseClass: created.baseClass,
      createdAt: created.createdAt.toISOString(),
      updatedAt: created.updatedAt.toISOString(),
      name: created.vietnameseName,
      kind,
      tint,
      samples: 0,
    };

    return sendCreated(res, formatted);
  } catch (err) {
    return next(err);
  }
});

/**
 * PUT /api/v1/labels/:id
 * Body: { vietnameseName?, baseClass? }
 */
labelsRouter.put('/:id', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { id } = req.params;
    const existing = await prisma.objectLabel.findUnique({
      where: { id },
    });

    if (!existing) {
      throw new NotFoundError(`Không tìm thấy nhãn với id '${id}'`);
    }

    const dataToUpdate: any = {};
    if (req.body.vietnameseName || req.body.name) {
      const newName = String(req.body.vietnameseName || req.body.name).trim();
      // Check if another label has this name
      const duplicate = await prisma.objectLabel.findFirst({
        where: {
          vietnameseName: newName,
          NOT: { id },
        },
      });
      if (duplicate) {
        throw new ConflictError(`Nhãn '${newName}' đã tồn tại.`);
      }
      dataToUpdate.vietnameseName = newName;
    }

    if (req.body.baseClass) {
      dataToUpdate.baseClass = String(req.body.baseClass).trim();
    }

    const updated = await prisma.objectLabel.update({
      where: { id },
      data: dataToUpdate,
      include: {
        _count: { select: { samples: true } },
      },
    });

    const kind = req.body.kind || inferKind(updated.baseClass, updated.vietnameseName);
    const tint = req.body.tint || DEFAULT_TINTS[0];

    const formatted = {
      id: updated.id,
      vietnameseName: updated.vietnameseName,
      baseClass: updated.baseClass,
      createdAt: updated.createdAt.toISOString(),
      updatedAt: updated.updatedAt.toISOString(),
      name: updated.vietnameseName,
      kind,
      tint,
      samples: updated._count.samples,
    };

    return sendSuccess(res, formatted);
  } catch (err) {
    return next(err);
  }
});

/**
 * DELETE /api/v1/labels/:id
 * Cascades to associated samples.
 */
labelsRouter.delete('/:id', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { id } = req.params;
    const existing = await prisma.objectLabel.findUnique({
      where: { id },
    });

    if (!existing) {
      throw new NotFoundError(`Không tìm thấy nhãn với id '${id}'`);
    }

    // Delete label (Prisma relation onDelete: Cascade will delete label_samples)
    await prisma.objectLabel.delete({
      where: { id },
    });

    return sendNoContent(res);
  } catch (err) {
    return next(err);
  }
});

/**
 * GET /api/v1/labels/:id/samples
 */
labelsRouter.get('/:id/samples', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { id } = req.params;
    const samples = await prisma.labelSample.findMany({
      where: { labelId: id },
      orderBy: { createdAt: 'desc' },
    });

    return sendSuccess(res, samples);
  } catch (err) {
    return next(err);
  }
});

export { labelsRouter };
