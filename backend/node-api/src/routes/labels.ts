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
import {
  DetectionLabelValidationError,
  type ObjectLabelDto,
} from '../detection/capabilities';
import {
  detectionCapabilityService,
  invalidateDetectionContext,
} from '../services/detectionCapabilityService';

const labelsRouter = Router();

function getBodyValue(body: unknown, key: string): unknown {
  return body !== null && typeof body === 'object' && !Array.isArray(body)
    ? (body as Record<string, unknown>)[key]
    : undefined;
}

function requiredNonblankString(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new BadRequestError(`${field} is required`);
  }
  return value.trim();
}

async function currentLabelDto(labelId: string): Promise<ObjectLabelDto> {
  const context = await detectionCapabilityService.loadDetectionContext();
  const index = context.labels.findIndex((label) => label.id === labelId);
  if (index < 0) {
    throw new NotFoundError(`Không tìm thấy nhãn với id '${labelId}'`);
  }
  return detectionCapabilityService.toObjectLabelDto(context.labels[index], context, index);
}

/**
 * GET /api/v1/labels
 * Returns all labels with sample count and UI formatting.
 */
labelsRouter.get('/', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const context = await detectionCapabilityService.loadDetectionContext();
    return sendSuccess(res, context.labels.map((record, index) =>
      detectionCapabilityService.toObjectLabelDto(record, context, index)));
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
    const vietnameseName = requiredNonblankString(
      getBodyValue(req.body, 'vietnameseName') ?? getBodyValue(req.body, 'name'),
      'vietnameseName',
    );
    const requestedBaseClass = requiredNonblankString(getBodyValue(req.body, 'baseClass'), 'baseClass');
    const baseClass = detectionCapabilityService.normalizeWritableLabel(vietnameseName, requestedBaseClass);

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
    invalidateDetectionContext();
    return sendCreated(res, await currentLabelDto(created.id));
  } catch (err) {
    if (err instanceof DetectionLabelValidationError) {
      return next(new BadRequestError(err.message, { reasonCode: err.reasonCode }));
    }
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

    const requestedName = getBodyValue(req.body, 'vietnameseName') ?? getBodyValue(req.body, 'name');
    const hasRequestedName = requestedName !== undefined;
    const hasRequestedBaseClass = getBodyValue(req.body, 'baseClass') !== undefined;
    const newName = hasRequestedName
      ? requiredNonblankString(requestedName, 'vietnameseName')
      : existing.vietnameseName;
    const requestedBaseClass = hasRequestedBaseClass
      ? requiredNonblankString(getBodyValue(req.body, 'baseClass'), 'baseClass')
      : existing.baseClass;
    const normalizedBaseClass = detectionCapabilityService.normalizeWritableLabel(newName, requestedBaseClass);

    const dataToUpdate: { vietnameseName?: string; baseClass?: string } = {};
    if (hasRequestedName) {
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

    if (hasRequestedBaseClass || normalizedBaseClass !== existing.baseClass) {
      dataToUpdate.baseClass = normalizedBaseClass;
    }

    const updated = await prisma.objectLabel.update({
      where: { id },
      data: dataToUpdate,
    });
    invalidateDetectionContext();
    return sendSuccess(res, await currentLabelDto(updated.id));
  } catch (err) {
    if (err instanceof DetectionLabelValidationError) {
      return next(new BadRequestError(err.message, { reasonCode: err.reasonCode }));
    }
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
    invalidateDetectionContext();

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
