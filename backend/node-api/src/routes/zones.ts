import { Request, Response, Router } from 'express';
import type { Prisma } from '@prisma/client';
import { prisma } from '../prisma/client';
import { sendCreated, sendError, sendNoContent, sendSuccess } from '../utils/response';

const zonesRouter = Router();
const AREA_CAMERA_ID = 'BAI-KIEM';
const RULE_TYPES = new Set(['PROHIBIT_SPECIFIED', 'ALLOW_SPECIFIED']);

interface PolygonPoint {
  x: number;
  y: number;
}

export interface ZoneDto {
  id: string;
  cameraId: 'BAI-KIEM';
  name: string;
  polygonPoints: PolygonPoint[];
  ruleType: 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED';
  targetLabels: string[];
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

interface ZoneWriteInput {
  name?: string;
  polygonPoints?: PolygonPoint[];
  ruleType?: 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED';
  targetLabels?: string[];
  isActive?: boolean;
}

type ZoneCreateInput = Omit<ZoneWriteInput, 'cameraId'>;

export class ZoneValidationError extends Error {}

function getSingleString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function isSingleQueryValue(value: unknown): boolean {
  return value === undefined || typeof value === 'string';
}

function requireAreaCameraId(value: unknown, required: boolean): 'BAI-KIEM' | undefined {
  if (value === undefined && !required) return undefined;
  if (value !== AREA_CAMERA_ID) {
    throw new ZoneValidationError('Only camera_id BAI-KIEM is supported for zone editing');
  }
  return AREA_CAMERA_ID;
}

function parseName(value: unknown): string {
  if (typeof value !== 'string') {
    throw new ZoneValidationError('name must be a string');
  }
  const name = value.trim();
  if (!name || name.length > 100) {
    throw new ZoneValidationError('name must contain 1 to 100 characters');
  }
  return name;
}

function parsePolygonPoint(value: unknown): PolygonPoint {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new ZoneValidationError('Each polygon point must be an object with x and y');
  }

  const { x, y } = value as { x?: unknown; y?: unknown };
  if (
    typeof x !== 'number'
    || typeof y !== 'number'
    || !Number.isFinite(x)
    || !Number.isFinite(y)
    || x < 0
    || x > 1
    || y < 0
    || y > 1
  ) {
    throw new ZoneValidationError('polygonPoints coordinates must be finite numbers between 0 and 1');
  }
  return { x, y };
}

export function parsePolygonPoints(value: unknown): PolygonPoint[] {
  if (!Array.isArray(value) || value.length < 3) {
    throw new ZoneValidationError('polygonPoints must contain at least 3 points');
  }
  return value.map(parsePolygonPoint);
}

function parseRuleType(value: unknown): 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED' {
  if (typeof value !== 'string' || !RULE_TYPES.has(value)) {
    throw new ZoneValidationError('ruleType must be PROHIBIT_SPECIFIED or ALLOW_SPECIFIED');
  }
  return value as 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED';
}

function parseTargetLabels(value: unknown): string[] {
  if (!Array.isArray(value)) {
    throw new ZoneValidationError('targetLabels must be an array of strings');
  }

  const seen = new Set<string>();
  const labels: string[] = [];
  for (const valueItem of value) {
    if (typeof valueItem !== 'string') {
      throw new ZoneValidationError('targetLabels must be an array of strings');
    }
    const label = valueItem.trim();
    if (!label || label.length > 100) {
      throw new ZoneValidationError('targetLabels entries must contain 1 to 100 characters');
    }
    const key = label.toLocaleLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      labels.push(label);
    }
  }
  return labels;
}

export function parseCreateZoneInput(body: unknown): Required<ZoneCreateInput> {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new ZoneValidationError('Request body must be an object');
  }
  const input = body as Record<string, unknown>;
  requireAreaCameraId(input.cameraId, true);
  return {
    name: parseName(input.name),
    polygonPoints: parsePolygonPoints(input.polygonPoints),
    ruleType: input.ruleType === undefined
      ? 'PROHIBIT_SPECIFIED'
      : parseRuleType(input.ruleType),
    targetLabels: input.targetLabels === undefined ? [] : parseTargetLabels(input.targetLabels),
    isActive: input.isActive === undefined
      ? true
      : (() => {
        if (typeof input.isActive !== 'boolean') {
          throw new ZoneValidationError('isActive must be a boolean');
        }
        return input.isActive;
      })(),
  };
}

export function parseUpdateZoneInput(body: unknown): ZoneWriteInput {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new ZoneValidationError('Request body must be an object');
  }
  const input = body as Record<string, unknown>;
  const allowedKeys = new Set(['name', 'polygonPoints', 'ruleType', 'targetLabels', 'isActive']);
  if (!Object.keys(input).some((key) => allowedKeys.has(key))) {
    throw new ZoneValidationError('Provide at least one zone field to update');
  }

  const update: ZoneWriteInput = {};
  if ('name' in input) update.name = parseName(input.name);
  if ('polygonPoints' in input) update.polygonPoints = parsePolygonPoints(input.polygonPoints);
  if ('ruleType' in input) update.ruleType = parseRuleType(input.ruleType);
  if ('targetLabels' in input) update.targetLabels = parseTargetLabels(input.targetLabels);
  if ('isActive' in input) {
    if (typeof input.isActive !== 'boolean') {
      throw new ZoneValidationError('isActive must be a boolean');
    }
    update.isActive = input.isActive;
  }
  return update;
}

function toZoneDto(zone: {
  id: string;
  cameraId: string;
  name: string;
  polygonPoints: Prisma.JsonValue;
  ruleType: string;
  targetLabels: Prisma.JsonValue;
  isActive: boolean;
  createdAt: Date;
  updatedAt: Date;
}): ZoneDto {
  return {
    id: zone.id,
    cameraId: AREA_CAMERA_ID,
    name: zone.name,
    polygonPoints: parsePolygonPoints(zone.polygonPoints),
    ruleType: parseRuleType(zone.ruleType),
    targetLabels: parseTargetLabels(zone.targetLabels),
    isActive: zone.isActive,
    createdAt: zone.createdAt.toISOString(),
    updatedAt: zone.updatedAt.toISOString(),
  };
}

function isPrismaError(error: unknown, code: string): boolean {
  return typeof error === 'object'
    && error !== null
    && 'code' in error
    && (error as { code?: unknown }).code === code;
}

async function getAreaZoneOrNull(id: string) {
  return prisma.zone.findFirst({
    where: { id, cameraId: AREA_CAMERA_ID },
  });
}

zonesRouter.get('/', async (req: Request, res: Response) => {
  try {
    if (!isSingleQueryValue(req.query.camera_id)) {
      return sendError(res, 400, 'VALIDATION_ERROR', 'camera_id must be a single string value');
    }
    requireAreaCameraId(getSingleString(req.query.camera_id), false);

    const zones = await prisma.zone.findMany({
      where: { cameraId: AREA_CAMERA_ID },
      orderBy: [{ updatedAt: 'desc' }, { id: 'desc' }],
    });
    return sendSuccess(res, zones.map(toZoneDto));
  } catch (error) {
    if (error instanceof ZoneValidationError) {
      return sendError(res, 400, 'VALIDATION_ERROR', error.message);
    }
    console.error('[zonesRouter] Failed to list BAI-KIEM zones:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to retrieve zones');
  }
});

zonesRouter.post('/', async (req: Request, res: Response) => {
  try {
    const input = parseCreateZoneInput(req.body);
    const zone = await prisma.zone.create({
      data: {
        cameraId: AREA_CAMERA_ID,
        name: input.name,
        polygonPoints: input.polygonPoints as unknown as Prisma.InputJsonValue,
        ruleType: input.ruleType,
        targetLabels: input.targetLabels as unknown as Prisma.InputJsonValue,
        isActive: input.isActive,
      },
    });
    return sendCreated(res, toZoneDto(zone));
  } catch (error) {
    if (error instanceof ZoneValidationError) {
      return sendError(res, 400, 'VALIDATION_ERROR', error.message);
    }
    if (isPrismaError(error, 'P2002')) {
      return sendError(res, 409, 'ZONE_NAME_CONFLICT', 'Zone name already exists for BAI-KIEM');
    }
    console.error('[zonesRouter] Failed to create BAI-KIEM zone:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to create zone');
  }
});

zonesRouter.put('/:id', async (req: Request, res: Response) => {
  try {
    const input = parseUpdateZoneInput(req.body);
    const existing = await getAreaZoneOrNull(req.params.id);
    if (!existing) {
      return sendError(res, 404, 'ZONE_NOT_FOUND', 'Zone was not found for BAI-KIEM');
    }

    const zone = await prisma.zone.update({
      where: { id: existing.id },
      data: {
        ...(input.name !== undefined ? { name: input.name } : {}),
        ...(input.polygonPoints !== undefined
          ? { polygonPoints: input.polygonPoints as unknown as Prisma.InputJsonValue }
          : {}),
        ...(input.ruleType !== undefined ? { ruleType: input.ruleType } : {}),
        ...(input.targetLabels !== undefined
          ? { targetLabels: input.targetLabels as unknown as Prisma.InputJsonValue }
          : {}),
        ...(input.isActive !== undefined ? { isActive: input.isActive } : {}),
      },
    });
    return sendSuccess(res, toZoneDto(zone));
  } catch (error) {
    if (error instanceof ZoneValidationError) {
      return sendError(res, 400, 'VALIDATION_ERROR', error.message);
    }
    if (isPrismaError(error, 'P2002')) {
      return sendError(res, 409, 'ZONE_NAME_CONFLICT', 'Zone name already exists for BAI-KIEM');
    }
    console.error('[zonesRouter] Failed to update BAI-KIEM zone:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to update zone');
  }
});

zonesRouter.delete('/:id', async (req: Request, res: Response) => {
  try {
    const existing = await getAreaZoneOrNull(req.params.id);
    if (!existing) {
      return sendError(res, 404, 'ZONE_NOT_FOUND', 'Zone was not found for BAI-KIEM');
    }

    await prisma.zone.delete({ where: { id: existing.id } });
    return sendNoContent(res);
  } catch (error) {
    console.error('[zonesRouter] Failed to delete BAI-KIEM zone:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to delete zone');
  }
});

export { zonesRouter, AREA_CAMERA_ID };
