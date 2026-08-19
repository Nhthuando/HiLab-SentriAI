/**
 * routes/samples.ts — Annotation Samples REST API Router (VS-SETTINGS-LABEL)
 *
 * Implements batch sample creation and management for object labeling (M3, AP-07):
 * - POST   /api/v1/samples/batch
 * - DELETE /api/v1/samples/:id
 */
import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../prisma/client';
import { BadRequestError, NotFoundError } from '../utils/errors';
import { sendCreated, sendNoContent, sendSuccess } from '../utils/response';

const samplesRouter = Router();

/**
 * GET /api/v1/samples
 * Returns all annotation samples from database.
 */
samplesRouter.get('/', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const records = await prisma.labelSample.findMany({
      orderBy: { createdAt: 'desc' },
      take: 200,
    });

    const formatted = records.map((r) => {
      const bbox = (r.bbox as any) || {};
      return {
        id: r.id,
        labelId: r.labelId,
        srcId: r.imagePath,
        x: bbox.x ?? 0,
        y: bbox.y ?? 0,
        w: bbox.w ?? 0,
        h: bbox.h ?? 0,
        frame: bbox.frame ?? null,
        session: 0,
      };
    });

    return sendSuccess(res, formatted);
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /api/v1/samples/batch
 * Body: { samples: Array<{ labelId, imagePath?, bbox: { x, y, w, h } | [x, y, w, h] }> }
 */
samplesRouter.post('/batch', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const rawSamples = req.body.samples;
    if (!Array.isArray(rawSamples) || rawSamples.length === 0) {
      throw new BadRequestError('samples must be a non-empty array');
    }

    // Get all valid label IDs
    const labelIds = Array.from(new Set(rawSamples.map((s) => s.labelId || s.label_id).filter(Boolean)));
    const validLabels = await prisma.objectLabel.findMany({
      where: { id: { in: labelIds } },
      select: { id: true },
    });
    const validLabelSet = new Set(validLabels.map((l) => l.id));

    const insertData: Array<{ labelId: string; imagePath: string; bbox: any }> = [];

    for (const item of rawSamples) {
      const labelId = item.labelId || item.label_id;
      if (!labelId || !validLabelSet.has(labelId)) {
        continue; // Skip invalid label reference
      }

      const imagePath = item.imagePath || item.image_path || item.srcId || '/data/samples/sample.jpg';
      const bbox = item.bbox || {
        x: item.x ?? 0,
        y: item.y ?? 0,
        w: item.w ?? 0,
        h: item.h ?? 0,
        frame: item.frame ?? null,
      };

      insertData.push({
        labelId,
        imagePath: String(imagePath),
        bbox,
      });
    }

    if (insertData.length === 0) {
      throw new BadRequestError('No valid samples with matching label IDs to insert');
    }

    const result = await prisma.labelSample.createMany({
      data: insertData,
    });

    return sendCreated(res, {
      count: result.count,
      created: result.count,
    });
  } catch (err) {
    return next(err);
  }
});

/**
 * DELETE /api/v1/samples/:id
 */
samplesRouter.delete('/:id', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { id } = req.params;
    const existing = await prisma.labelSample.findUnique({
      where: { id },
    });

    if (!existing) {
      throw new NotFoundError(`Không tìm thấy mẫu với id '${id}'`);
    }

    await prisma.labelSample.delete({
      where: { id },
    });

    return sendNoContent(res);
  } catch (err) {
    return next(err);
  }
});

export { samplesRouter };
