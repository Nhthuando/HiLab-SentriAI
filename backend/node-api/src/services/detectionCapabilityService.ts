import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import {
  type ActiveModelParseResult,
  type DetectionContext,
  type ObjectLabelDto,
  normalizeWritableLabel,
  parseActiveModelResult,
  resolveRecordCapability,
  toObjectLabelDto,
} from '../detection/capabilities';
import {
  type DetectionControlRepository,
  PrismaDetectionControlRepository,
} from '../repositories/DetectionControlRepository';

interface ConfiguredModelContext {
  activeModelResult: ActiveModelParseResult;
  artifactPath: string;
  allowPartialUnified: boolean;
}

interface DetectionContextCacheOptions {
  ttlMs?: number;
  now?: () => number;
}

function hasOwnerApprovedPartialUnified(metrics: unknown): boolean {
  if (typeof metrics !== 'object' || metrics === null || Array.isArray(metrics)) return false;
  const approval = (metrics as Record<string, unknown>).manualProductionApproval;
  return typeof approval === 'object' && approval !== null && !Array.isArray(approval)
    && (approval as Record<string, unknown>).approved === true
    && (approval as Record<string, unknown>).allowPartialUnified === true;
}

export function hasConfiguredManualApproval(metrics: unknown, expectedSha256: string): boolean {
  if (!hasOwnerApprovedPartialUnified(metrics)) return false;
  const approval = (metrics as Record<string, unknown>).manualProductionApproval as Record<string, unknown>;
  return typeof approval.artifactSha256 === 'string'
    && approval.artifactSha256.toLowerCase() === expectedSha256;
}

function configuredModelContext(): ConfiguredModelContext | null {
  if (!['1', 'true', 'yes', 'on'].includes((process.env.CUSTOM_AUGMENT_FORCE_DEFAULT ?? '').trim().toLowerCase())) {
    return null;
  }
  const artifactSetting = (process.env.CUSTOM_AUGMENT_ARTIFACT ?? '').trim();
  const versionKey = (process.env.CUSTOM_AUGMENT_VERSION_KEY ?? '').trim();
  const expectedSha256 = (process.env.CUSTOM_AUGMENT_SHA256 ?? '').trim().toLowerCase();
  if (!artifactSetting || !versionKey || !/^[0-9a-f]{64}$/.test(expectedSha256)) return null;

  const dataRoot = path.resolve(__dirname, '../../../data');
  const artifactPath = path.resolve(dataRoot, artifactSetting);
  const relative = path.relative(dataRoot, artifactPath);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) return null;
  try {
    const labelsPath = path.join(path.dirname(artifactPath), 'labels.json');
    const evaluationPath = path.join(path.dirname(artifactPath), 'evaluation.json');
    const artifact = fs.readFileSync(artifactPath);
    const labels = JSON.parse(fs.readFileSync(labelsPath, 'utf8')) as unknown;
    const evaluation = JSON.parse(fs.readFileSync(evaluationPath, 'utf8')) as unknown;
    if (typeof labels !== 'object' || labels === null || Array.isArray(labels) || Object.keys(labels).length === 0) return null;
    if (typeof evaluation !== 'object' || evaluation === null || Array.isArray(evaluation)) return null;
    const metrics = evaluation as Record<string, unknown>;
    const qualityGate = metrics.qualityGate;
    const baseRegression = metrics.baseRegression;
    const manualCandidate = ['1', 'true', 'yes', 'on'].includes(
      (process.env.CUSTOM_AUGMENT_MANUAL_CANDIDATE ?? '').trim().toLowerCase(),
    ) && hasConfiguredManualApproval(metrics, expectedSha256);
    if (
      typeof qualityGate !== 'object' || qualityGate === null
      || ((qualityGate as Record<string, unknown>).passed !== true && !manualCandidate)
      || typeof baseRegression !== 'object' || baseRegression === null || (baseRegression as Record<string, unknown>).passed !== true
    ) return null;
    // Force the same full artifact read/checksum work as the worker bridge, so
    // API capability and runtime routing cannot disagree about a missing file.
    const artifactSha256 = crypto.createHash('sha256').update(artifact).digest('hex');
    if (artifactSha256 !== expectedSha256) return null;
    const runtimeMode = metrics.runtimeMode === 'UNIFIED' ? 'UNIFIED' : 'SUPPLEMENTAL';
    return {
      activeModelResult: parseActiveModelResult({
        id: 'configured-runtime-model',
        trainingJobId: 'configured-runtime-model',
        versionKey,
        baseModel: 'configured',
        artifactPath,
        artifactSha256,
        status: 'ACTIVE',
        evaluationMetrics: { labelMap: labels, runtimeMode },
        evaluatedAt: null,
        activatedAt: null,
        createdAt: new Date(0),
      }),
      artifactPath,
      allowPartialUnified: hasOwnerApprovedPartialUnified(metrics),
    };
  } catch {
    return null;
  }
}

/** Framework-independent capability decisions over an injectable read repository. */
export class DetectionCapabilityService {
  private readonly ttlMs: number;
  private readonly now: () => number;
  private generation = 0;
  private cache: {
    value: DetectionContext;
    expiresAt: number;
    generation: number;
  } | null = null;
  private inFlight: {
    promise: Promise<DetectionContext>;
    generation: number;
  } | null = null;

  constructor(
    private readonly repository: DetectionControlRepository,
    options: DetectionContextCacheOptions = {},
  ) {
    this.ttlMs = Math.max(0, options.ttlMs ?? 30_000);
    this.now = options.now ?? Date.now;
  }

  invalidate(): void {
    this.generation += 1;
    this.cache = null;
  }

  async loadDetectionContext(): Promise<DetectionContext> {
    const generation = this.generation;
    const cached = this.cache;
    if (
      cached !== null
      && cached.generation === generation
      && cached.expiresAt > this.now()
    ) {
      return cached.value;
    }
    if (this.inFlight?.generation === generation) {
      return this.inFlight.promise;
    }

    const promise = this.loadFreshDetectionContext()
      .then((context) => {
        if (this.generation === generation) {
          this.cache = {
            value: context,
            expiresAt: this.now() + this.ttlMs,
            generation,
          };
        }
        return context;
      })
      .finally(() => {
        if (this.inFlight?.promise === promise) {
          this.inFlight = null;
        }
      });
    this.inFlight = { promise, generation };
    return promise;
  }

  private async loadFreshDetectionContext(): Promise<DetectionContext> {
    const [activeRecord, labels] = await Promise.all([
      this.repository.findActiveModel(),
      this.repository.listLabelsWithSampleCount(),
    ]);
    const configured = activeRecord === null ? configuredModelContext() : null;
    const parsedActiveModelResult = configured?.activeModelResult ?? parseActiveModelResult(activeRecord);
    const allowPartialUnified = configured?.allowPartialUnified
      ?? hasOwnerApprovedPartialUnified(activeRecord?.evaluationMetrics);
    const unifiedCoverageIsIncomplete = parsedActiveModelResult.activeModel?.runtimeMode === 'UNIFIED'
      && labels.some((label) => resolveRecordCapability({
        vietnameseName: label.vietnameseName,
        baseClass: label.baseClass,
      }, parsedActiveModelResult).reasonCode === 'UNIFIED_CLASS_NOT_IN_ACTIVE_MODEL');
    // A unified artifact replaces the base model, so partial coverage would
    // silently disable registry classes. Reject that artifact as a whole and
    // preserve only the safe base-COCO fallback.
    const activeModelResult = unifiedCoverageIsIncomplete && !allowPartialUnified
      ? { activeModel: null, invalidManifest: true }
      : parsedActiveModelResult;
    const capabilitiesByName = new Map(labels.map((label) => [
      label.vietnameseName,
      resolveRecordCapability({
        vietnameseName: label.vietnameseName,
        baseClass: label.baseClass,
      }, activeModelResult),
    ]));

    return {
      activeModel: activeModelResult.activeModel,
      activeArtifactPath: activeModelResult.activeModel === null
        ? null
        : activeRecord?.artifactPath ?? configured?.artifactPath ?? null,
      labels,
      capabilitiesByName,
    };
  }

  toObjectLabelDto(
    record: Parameters<typeof toObjectLabelDto>[0],
    context: DetectionContext,
    index: number,
  ): ObjectLabelDto {
    const capability = context.capabilitiesByName.get(record.vietnameseName);
    if (capability === undefined) {
      throw new Error(`Missing detection capability for label '${record.vietnameseName}'`);
    }
    return toObjectLabelDto(record, capability, index);
  }

  normalizeWritableLabel(vietnameseName: string, baseClass: string): string {
    return normalizeWritableLabel(vietnameseName, baseClass);
  }
}

export const detectionCapabilityService = new DetectionCapabilityService(new PrismaDetectionControlRepository());

export async function loadDetectionContext(): Promise<DetectionContext> {
  return detectionCapabilityService.loadDetectionContext();
}

export function invalidateDetectionContext(): void {
  detectionCapabilityService.invalidate();
}
