import assert from 'assert';
import type { ModelVersion, ObjectLabel } from '@prisma/client';
import {
  DetectionLabelValidationError,
  parseActiveModel,
  parseActiveModelResult,
} from '../detection/capabilities';
import { DETECTION_TAXONOMY } from '../detection/taxonomy';
import type {
  DetectionControlRepository,
  ObjectLabelWithSampleCount,
} from '../repositories/DetectionControlRepository';
import { DetectionCapabilityService } from '../services/detectionCapabilityService';

function label(overrides: Partial<ObjectLabelWithSampleCount> = {}): ObjectLabelWithSampleCount {
  return {
    id: 'label-1',
    vietnameseName: 'Xe nâng container',
    baseClass: 'reach_stacker',
    createdAt: new Date('2026-08-22T00:00:00.000Z'),
    updatedAt: new Date('2026-08-22T00:00:00.000Z'),
    _count: { samples: 0 },
    ...overrides,
  };
}

function activeModel(evaluationMetrics: ModelVersion['evaluationMetrics']): ModelVersion {
  return {
    id: 'model-id',
    trainingJobId: 'job-id',
    versionKey: 'custom-v1',
    baseModel: 'yolo11n.pt',
    artifactPath: 'training/models/custom-v1/best.pt',
    artifactSha256: 'a'.repeat(64),
    status: 'ACTIVE',
    evaluationMetrics,
    evaluatedAt: new Date('2026-08-22T00:00:00.000Z'),
    activatedAt: new Date('2026-08-22T00:01:00.000Z'),
    createdAt: new Date('2026-08-22T00:00:00.000Z'),
  };
}

class FakeDetectionControlRepository implements DetectionControlRepository {
  constructor(
    private readonly model: ModelVersion | null,
    private readonly labels: ObjectLabelWithSampleCount[],
  ) {}

  async findActiveModel(): Promise<ModelVersion | null> {
    return this.model;
  }

  async listLabelsWithSampleCount(): Promise<ObjectLabelWithSampleCount[]> {
    return this.labels;
  }
}

const malformedMetricCases: Array<[string, ModelVersion['evaluationMetrics']]> = [
  ['null metrics', null],
  ['array metrics', []],
  ['missing labelMap', { precision: 0.9 }],
  ['array labelMap', { labelMap: [] }],
  ['non-string mapped class', { labelMap: { 'Xe nâng container': 4 } }],
  ['invalid mapped canonical class', { labelMap: { 'Xe nâng container': 'container' } }],
];

for (const [name, metrics] of malformedMetricCases) {
  const record = activeModel(metrics);
  assert.equal(parseActiveModel(record), null, `${name} must not produce an active model`);
  assert.equal(parseActiveModelResult(record).invalidManifest, true, `${name} must be marked malformed`);
}

const validRecord = activeModel({
  labelMap: { 'Xe nâng container': 'reach stacker' },
  map50: 0.9,
});
assert.deepStrictEqual(parseActiveModel(validRecord), {
  versionKey: 'custom-v1',
  labelMap: { 'Xe nâng container': 'reach stacker' },
  runtimeMode: 'SUPPLEMENTAL',
});
assert.equal(parseActiveModelResult(null).invalidManifest, false, 'no active record is not malformed');

async function runServiceTests(): Promise<void> {
  const malformedService = new DetectionCapabilityService(new FakeDetectionControlRepository(
    activeModel({ labelMap: { 'Xe nâng container': 4 } }),
    [label()],
  ));
  const malformedContext = await malformedService.loadDetectionContext();
  const malformedCapability = malformedContext.capabilitiesByName.get('Xe nâng container');
  assert.deepStrictEqual(malformedCapability, {
    canonicalClass: 'reach_stacker',
    detectionSource: 'UNAVAILABLE',
    isDetectable: false,
    activeModelVersion: null,
    reasonCode: 'INVALID_ACTIVE_MANIFEST',
    reasonText: 'Model custom đang hoạt động có manifest không hợp lệ',
  });
  assert.equal(malformedContext.activeArtifactPath, null, 'malformed active models must not expose an artifact to runtime');

  const customService = new DetectionCapabilityService(new FakeDetectionControlRepository(
    validRecord,
    [label(), label({ id: 'label-2', vietnameseName: 'Xe tải', baseClass: 'truck', _count: { samples: 10_000 } })],
  ));
  const context = await customService.loadDetectionContext();
  assert.deepStrictEqual(context.capabilitiesByName.get('Xe nâng container'), {
    canonicalClass: 'reach_stacker',
    detectionSource: 'CUSTOM',
    isDetectable: true,
    activeModelVersion: 'custom-v1',
    reasonCode: 'ACTIVE_CUSTOM_CLASS',
    reasonText: 'Nhận diện bởi model custom custom-v1',
  });
  assert.equal(context.capabilitiesByName.get('Xe tải')?.detectionSource, 'COCO', 'COCO owns truck even if a custom model is active');
  assert.equal(context.activeArtifactPath, 'training/models/custom-v1/best.pt');

  const unifiedRecord = activeModel({
    runtimeMode: 'UNIFIED',
    labelMap: {
      person: 'person',
      truck: 'truck',
      reach_stacker: 'reach_stacker',
    },
  });
  const unifiedContext = await new DetectionCapabilityService(new FakeDetectionControlRepository(
    unifiedRecord,
    [
      label({ id: 'person', vietnameseName: 'Người', baseClass: 'person' }),
      label({ id: 'truck', vietnameseName: 'Xe tải', baseClass: 'truck' }),
      label(),
    ],
  )).loadDetectionContext();
  assert.equal(unifiedContext.activeModel?.runtimeMode, 'UNIFIED');
  assert.equal(unifiedContext.capabilitiesByName.get('Xe tải')?.detectionSource, 'CUSTOM');
  assert.equal(unifiedContext.capabilitiesByName.get('Xe tải')?.reasonCode, 'ACTIVE_UNIFIED_CLASS');

  const incompleteUnifiedContext = await new DetectionCapabilityService(new FakeDetectionControlRepository(
    activeModel({
      runtimeMode: 'UNIFIED',
      labelMap: { person: 'person', reach_stacker: 'reach_stacker' },
    }),
    [
      label({
        id: 'person',
        vietnameseName: DETECTION_TAXONOMY.recommendedDisplayNames.person,
        baseClass: 'person',
      }),
      label({
        id: 'truck',
        vietnameseName: DETECTION_TAXONOMY.recommendedDisplayNames.truck,
        baseClass: 'truck',
      }),
      label(),
    ],
  )).loadDetectionContext();
  assert.equal(incompleteUnifiedContext.activeModel, null);
  assert.equal(incompleteUnifiedContext.activeArtifactPath, null);
  assert.equal(incompleteUnifiedContext.capabilitiesByName.get(incompleteUnifiedContext.labels[0].vietnameseName)?.detectionSource, 'COCO');
  assert.equal(incompleteUnifiedContext.capabilitiesByName.get(incompleteUnifiedContext.labels[1].vietnameseName)?.detectionSource, 'COCO');
  assert.equal(incompleteUnifiedContext.capabilitiesByName.get(incompleteUnifiedContext.labels[2].vietnameseName)?.reasonCode, 'INVALID_ACTIVE_MANIFEST');

  const approvedPartialUnifiedContext = await new DetectionCapabilityService(new FakeDetectionControlRepository(
    activeModel({
      runtimeMode: 'UNIFIED',
      labelMap: { person: 'person', reach_stacker: 'reach_stacker' },
      manualProductionApproval: {
        approved: true,
        allowPartialUnified: true,
      },
    }),
    [
      label({
        id: 'person',
        vietnameseName: DETECTION_TAXONOMY.recommendedDisplayNames.person,
        baseClass: 'person',
      }),
      label({
        id: 'truck',
        vietnameseName: DETECTION_TAXONOMY.recommendedDisplayNames.truck,
        baseClass: 'truck',
      }),
      label(),
    ],
  )).loadDetectionContext();
  assert.equal(approvedPartialUnifiedContext.activeModel?.runtimeMode, 'UNIFIED');
  assert.equal(approvedPartialUnifiedContext.activeArtifactPath, 'training/models/custom-v1/best.pt');
  assert.equal(approvedPartialUnifiedContext.capabilitiesByName.get(approvedPartialUnifiedContext.labels[0].vietnameseName)?.reasonCode, 'ACTIVE_UNIFIED_CLASS');
  assert.equal(approvedPartialUnifiedContext.capabilitiesByName.get(approvedPartialUnifiedContext.labels[1].vietnameseName)?.reasonCode, 'UNIFIED_CLASS_NOT_IN_ACTIVE_MODEL');
  assert.equal(approvedPartialUnifiedContext.capabilitiesByName.get(approvedPartialUnifiedContext.labels[2].vietnameseName)?.reasonCode, 'ACTIVE_UNIFIED_CLASS');

  const legacyReadService = new DetectionCapabilityService(new FakeDetectionControlRepository(
    activeModel({ labelMap: { 'Xe nâng': 'reach stacker' } }),
    [label({ vietnameseName: 'Xe nâng', baseClass: 'truck' })],
  ));
  assert.deepStrictEqual(
    (await legacyReadService.loadDetectionContext()).capabilitiesByName.get('Xe nâng'),
    {
      canonicalClass: 'reach_stacker',
      detectionSource: 'CUSTOM',
      isDetectable: true,
      activeModelVersion: 'custom-v1',
      reasonCode: 'ACTIVE_CUSTOM_LEGACY_LABEL',
      reasonText: 'Nhận diện bởi model custom custom-v1; nhãn legacy được định nghĩa bởi manifest',
    },
    'an exact reviewed manifest may repair an existing legacy read without relaxing write validation',
  );

  const dto = customService.toObjectLabelDto(context.labels[0], context, 0);
  assert.equal(dto.samples, 0, 'sample count remains display-only');
  assert.equal(dto.detectionSource, 'CUSTOM');
  assert.equal(dto.canonicalClass, 'reach_stacker');
  assert.equal(dto.capabilityReasonCode, 'ACTIVE_CUSTOM_CLASS');

  assert.equal(customService.normalizeWritableLabel('Xe nâng container', 'reach stacker'), 'reach_stacker');
  assert.equal(customService.normalizeWritableLabel('Xe đầu kéo container', 'container_truck'), 'container_truck');
  assert.equal(customService.normalizeWritableLabel('Container tĩnh', 'shipping_container'), 'shipping_container');
  assert.equal(customService.normalizeWritableLabel('Xe tải', 'truck'), 'truck');
  for (const [canonicalClass, displayName] of Object.entries(DETECTION_TAXONOMY.recommendedDisplayNames)) {
    assert.equal(
      customService.normalizeWritableLabel(displayName, canonicalClass),
      canonicalClass,
      `${displayName} must be writable only for its reserved canonical class`,
    );
  }
  assert.equal(customService.normalizeWritableLabel('  XE TẢI  ', 'truck'), 'truck');
  assert.equal(customService.normalizeWritableLabel('Xe kéo sân bãi', 'yard_tug'), 'yard_tug');
  for (const [name, expectedReason] of [
    ['Container', 'AMBIGUOUS_CONTAINER'],
    ['not valid!', 'INVALID_CANONICAL_CLASS'],
  ] as const) {
    assert.throws(
      () => customService.normalizeWritableLabel(name, name),
      (error: unknown) => error instanceof DetectionLabelValidationError && error.reasonCode === expectedReason,
      `${name} must not be persisted as a canonical label`,
    );
  }
  assert.throws(
    () => customService.normalizeWritableLabel('Xe nâng', 'truck'),
    (error: unknown) => error instanceof DetectionLabelValidationError
      && error.reasonCode === 'LEGACY_NAME_CLASS_MISMATCH',
    'legacy Vietnamese display constraints must be enforced on writes',
  );
  for (const [name, baseClass] of [
    ['Xe đầu kéo container', 'truck'],
    ['Container tĩnh', 'truck'],
    ['Xe nâng container', 'truck'],
    ['Xe tải', 'car'],
  ] as const) {
    assert.throws(
      () => customService.normalizeWritableLabel(name, baseClass),
      (error: unknown) => error instanceof DetectionLabelValidationError
        && error.reasonCode === 'RESERVED_DISPLAY_NAME_CLASS_MISMATCH',
      `${name} must only be stored with its reserved canonical class`,
    );
  }

  const zeroCountService = new DetectionCapabilityService(new FakeDetectionControlRepository(
    validRecord,
    [label({ _count: { samples: 0 } })],
  ));
  const manyCountService = new DetectionCapabilityService(new FakeDetectionControlRepository(
    validRecord,
    [label({ _count: { samples: 10_000 } })],
  ));
  const zeroCountCapability = (await zeroCountService.loadDetectionContext()).capabilitiesByName.get('Xe nâng container');
  const manyCountCapability = (await manyCountService.loadDetectionContext()).capabilitiesByName.get('Xe nâng container');
  assert.deepStrictEqual(manyCountCapability, zeroCountCapability, 'repository sample counts must not affect capabilities');
}

runServiceTests()
  .then(() => console.log('label capabilities: PASS (manifest parsing, DTOs, and DI service)'))
  .catch((error: unknown) => {
    console.error(error);
    process.exitCode = 1;
  });
