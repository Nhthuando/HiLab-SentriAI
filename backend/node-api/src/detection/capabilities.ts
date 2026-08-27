import type { ModelVersion, ObjectLabel } from '@prisma/client';
import {
  DetectionInputValidationError,
  type ActiveModelInput,
  type CapabilityLabelInput,
  type DetectionCapability,
  type DetectionSource,
  normalizeCanonicalClass,
  parseActiveModelInput,
  resolveLabelCapability,
} from './taxonomy';
import type { ObjectLabelWithSampleCount } from '../repositories/DetectionControlRepository';

export interface ObjectLabelDto {
  id: string;
  vietnameseName: string;
  baseClass: string;
  createdAt: string;
  updatedAt: string;
  name: string;
  kind: 'xe' | 'nguoi' | 'tinh';
  tint: string;
  samples: number;
  canonicalClass: string | null;
  detectionSource: DetectionSource;
  isDetectable: boolean;
  activeModelVersion: string | null;
  capabilityReason: string;
  capabilityReasonCode: string;
}

export interface DetectionContext {
  activeModel: ActiveModelInput | null;
  activeArtifactPath: string | null;
  labels: ObjectLabelWithSampleCount[];
  capabilitiesByName: Map<string, DetectionCapability>;
}

export interface ActiveModelParseResult {
  activeModel: ActiveModelInput | null;
  invalidManifest: boolean;
}

export type CapabilityLabelRecord = Pick<CapabilityLabelInput, 'vietnameseName' | 'baseClass'>;

const DEFAULT_TINTS = [
  '#3b82f6', '#10b981', '#06b6d4', '#a855f7', '#f59e0b', '#f43f5e', '#8b5cf6', '#64748b',
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function unavailableForInvalidManifest(canonicalClass: string): DetectionCapability {
  return {
    canonicalClass,
    detectionSource: 'UNAVAILABLE',
    isDetectable: false,
    activeModelVersion: null,
    reasonCode: 'INVALID_ACTIVE_MANIFEST',
    reasonText: 'Model custom đang hoạt động có manifest không hợp lệ',
  };
}

/**
 * Converts the existing JSON evaluation metrics into the strict Task 1 active
 * model input. A malformed persisted manifest is intentionally non-throwing so
 * that label listing remains available and fails closed for custom classes.
 */
export function parseActiveModelResult(record: ModelVersion | null): ActiveModelParseResult {
  if (record === null) {
    return { activeModel: null, invalidManifest: false };
  }
  if (!isRecord(record.evaluationMetrics) || !Object.prototype.hasOwnProperty.call(record.evaluationMetrics, 'labelMap')) {
    return { activeModel: null, invalidManifest: true };
  }

  try {
    return {
      activeModel: parseActiveModelInput({
        versionKey: record.versionKey,
        labelMap: record.evaluationMetrics.labelMap,
        runtimeMode: record.evaluationMetrics.runtimeMode ?? 'SUPPLEMENTAL',
      }),
      invalidManifest: false,
    };
  } catch (error) {
    if (error instanceof DetectionInputValidationError) {
      return { activeModel: null, invalidManifest: true };
    }
    throw error;
  }
}

/** Returns a valid Task 1 active-model input, or null for absent/malformed records. */
export function parseActiveModel(record: ModelVersion | null): ActiveModelInput | null {
  return parseActiveModelResult(record).activeModel;
}

/** Resolve a record against a parsed active manifest without consulting sample contents/counts. */
export function resolveRecordCapability(
  record: CapabilityLabelRecord,
  activeModelResult: ActiveModelParseResult,
): DetectionCapability {
  const label = {
    vietnameseName: record.vietnameseName,
    baseClass: record.baseClass,
  };
  const withoutActiveModel = resolveLabelCapability(label, null);
  if (
    withoutActiveModel.detectionSource === 'COCO'
    && activeModelResult.activeModel?.runtimeMode !== 'UNIFIED'
  ) {
    return withoutActiveModel;
  }
  if (activeModelResult.activeModel?.runtimeMode === 'UNIFIED') {
    return resolveLabelCapability(label, activeModelResult.activeModel);
  }
  if (
    activeModelResult.activeModel !== null
    && withoutActiveModel.reasonCode === 'LEGACY_NAME_CLASS_MISMATCH'
  ) {
    return resolveLabelCapability(label, activeModelResult.activeModel);
  }
  if (withoutActiveModel.canonicalClass === null) return withoutActiveModel;
  if (activeModelResult.invalidManifest) {
    return unavailableForInvalidManifest(withoutActiveModel.canonicalClass);
  }
  return resolveLabelCapability(label, activeModelResult.activeModel);
}

export function toObjectLabelDto(
  record: ObjectLabel & { _count: { samples: number } },
  capability: DetectionCapability,
  index: number,
): ObjectLabelDto {
  const combined = `${record.baseClass} ${record.vietnameseName}`.toLocaleLowerCase();
  const kind: 'xe' | 'nguoi' | 'tinh' = capability.canonicalClass === 'shipping_container'
    ? 'tinh'
    : combined.includes('người') || combined.includes('person')
      || combined.includes('worker') || combined.includes('walker')
      ? 'nguoi'
      : 'xe';

  return {
    id: record.id,
    vietnameseName: record.vietnameseName,
    baseClass: record.baseClass,
    createdAt: record.createdAt.toISOString(),
    updatedAt: record.updatedAt.toISOString(),
    name: record.vietnameseName,
    kind,
    tint: DEFAULT_TINTS[index % DEFAULT_TINTS.length],
    samples: record._count.samples,
    canonicalClass: capability.canonicalClass,
    detectionSource: capability.detectionSource,
    isDetectable: capability.isDetectable,
    activeModelVersion: capability.activeModelVersion,
    capabilityReason: capability.reasonText,
    capabilityReasonCode: capability.reasonCode,
  };
}

export class DetectionLabelValidationError extends Error {
  constructor(
    readonly reasonCode: string,
    message: string,
  ) {
    super(message);
    this.name = 'DetectionLabelValidationError';
  }
}

/** Validate and canonicalize a write without requiring a custom model to exist. */
export function normalizeWritableLabel(vietnameseName: string, baseClass: string): string {
  const canonicalClass = normalizeCanonicalClass(baseClass);
  if (canonicalClass === null) {
    const reasonCode = baseClass.trim().toLocaleLowerCase() === 'container'
      ? 'AMBIGUOUS_CONTAINER'
      : 'INVALID_CANONICAL_CLASS';
    throw new DetectionLabelValidationError(reasonCode, `baseClass '${baseClass}' không hợp lệ`);
  }

  const capability = resolveLabelCapability({ vietnameseName, baseClass: canonicalClass }, null);
  if (capability.reasonCode === 'AMBIGUOUS_CONTAINER'
    || capability.reasonCode === 'INVALID_CANONICAL_CLASS'
    || capability.reasonCode === 'LEGACY_NAME_CLASS_MISMATCH'
    || capability.reasonCode === 'RESERVED_DISPLAY_NAME_CLASS_MISMATCH') {
    throw new DetectionLabelValidationError(capability.reasonCode, capability.reasonText);
  }
  return canonicalClass;
}
