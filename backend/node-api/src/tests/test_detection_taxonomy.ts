import assert from 'assert';
import fs from 'fs';
import path from 'path';

import {
  decodeDetectionTaxonomy,
  DETECTION_TAXONOMY,
  DetectionCapability,
  DetectionInputValidationError,
  DetectionTaxonomyValidationError,
  parseActiveModelInput,
  parseRegistryLabelInput,
  resolveLabelCapability,
} from '../detection/taxonomy';

const unifiedModel = {
  versionKey: 'unified-v1',
  runtimeMode: 'UNIFIED',
  labelMap: { truck: 'truck', reach_stacker: 'reach_stacker' },
};
assert.deepStrictEqual(
  resolveLabelCapability({ vietnameseName: 'Xe tải', baseClass: 'truck' }, unifiedModel),
  {
    canonicalClass: 'truck',
    detectionSource: 'CUSTOM',
    isDetectable: true,
    activeModelVersion: 'unified-v1',
    reasonCode: 'ACTIVE_UNIFIED_CLASS',
    reasonText: 'Nhận diện bởi model unified unified-v1',
  },
);
const missingUnifiedCar = resolveLabelCapability(
  { vietnameseName: 'Xe con', baseClass: 'car' },
  unifiedModel,
);
assert.equal(missingUnifiedCar.isDetectable, false);
assert.equal(missingUnifiedCar.reasonCode, 'UNIFIED_CLASS_NOT_IN_ACTIVE_MODEL');
assert.equal(
  parseActiveModelInput({ versionKey: 'legacy-v1', labelMap: { reach: 'reach_stacker' } }).runtimeMode,
  'SUPPLEMENTAL',
);
assert.throws(
  () => parseActiveModelInput({ versionKey: 'bad-v1', runtimeMode: 'PRIMARY', labelMap: { reach: 'reach_stacker' } }),
  DetectionInputValidationError,
);

assert.deepStrictEqual(
  resolveLabelCapability(
    { vietnameseName: 'Xe nâng', baseClass: 'truck' },
    { versionKey: 'custom-legacy', labelMap: { 'Xe nâng': 'reach stacker' } },
  ),
  {
    canonicalClass: 'reach_stacker',
    detectionSource: 'CUSTOM',
    isDetectable: true,
    activeModelVersion: 'custom-legacy',
    reasonCode: 'ACTIVE_CUSTOM_LEGACY_LABEL',
    reasonText: 'Nhận diện bởi model custom custom-legacy; nhãn legacy được định nghĩa bởi manifest',
  },
);

interface TaxonomyCase {
  name: string;
  label: unknown;
  activeModel: unknown | null;
  expected: DetectionCapability;
}

interface MalformedInputCase {
  name: string;
  target: 'registry' | 'activeModel';
  value: unknown;
  expectedCategory: 'INPUT_VALIDATION';
}

interface MalformedTaxonomyCase {
  name: string;
  path: string[];
  value?: unknown;
  delete?: boolean;
  expectedCategory: 'TAXONOMY_VALIDATION';
}

interface TaxonomyCasesFile {
  schemaVersion: number;
  cases: TaxonomyCase[];
  malformedInputs: MalformedInputCase[];
  malformedTaxonomy: MalformedTaxonomyCase[];
}

const casesPath = path.resolve(__dirname, '../../../config/detection-taxonomy-cases.json');
const fixture = JSON.parse(fs.readFileSync(casesPath, 'utf8')) as TaxonomyCasesFile;

assert.equal(fixture.schemaVersion, 1);
assert.equal(fixture.cases.length, 19, 'the original 13 parity cases, reserved-name parity, shared-whitespace and all U+001C edge cases');

for (const testCase of fixture.cases) {
  assert.deepStrictEqual(
    resolveLabelCapability(testCase.label, testCase.activeModel),
    testCase.expected,
    testCase.name,
  );
}

const zeroSampleResult = resolveLabelCapability(
  { vietnameseName: 'Xe nâng container', baseClass: 'reach_stacker', sampleCount: 0 },
  { versionKey: 'custom-v1', labelMap: { 'Xe nâng container': 'reach_stacker' } },
);
const manySampleResult = resolveLabelCapability(
  { vietnameseName: 'Xe nâng container', baseClass: 'reach_stacker', sampleCount: 10_000 },
  { versionKey: 'custom-v1', labelMap: { 'Xe nâng container': 'reach_stacker' } },
);
assert.deepStrictEqual(manySampleResult, zeroSampleResult, 'sampleCount must not affect runtime capability');

const malformedFakeCountResult = resolveLabelCapability(
  {
    vietnameseName: 'Xe nâng container',
    baseClass: 'reach_stacker',
    sampleCount: { malformed: true },
    _count: { samples: Number.NaN },
  },
  { versionKey: 'custom-v1', labelMap: { 'Xe nâng container': 'reach_stacker' } },
);
assert.deepStrictEqual(
  malformedFakeCountResult,
  zeroSampleResult,
  'malformed DTO-only sample count fields must not affect runtime capability',
);

function assertInputCategory(action: () => unknown, name: string): void {
  assert.throws(action, (error: unknown) =>
    error instanceof DetectionInputValidationError && error.category === 'INPUT_VALIDATION', name);
}

for (const testCase of fixture.malformedInputs) {
  assertInputCategory(
    () => (testCase.target === 'registry' ? parseRegistryLabelInput(testCase.value) : parseActiveModelInput(testCase.value)),
    testCase.name,
  );
}

const taxonomyPath = path.resolve(__dirname, '../../../config/detection-taxonomy.json');
const rawTaxonomy = JSON.parse(fs.readFileSync(taxonomyPath, 'utf8')) as Record<string, unknown>;

function clonedTaxonomy(): Record<string, unknown> {
  return JSON.parse(JSON.stringify(rawTaxonomy)) as Record<string, unknown>;
}

function mutateAtPath(document: Record<string, unknown>, testCase: MalformedTaxonomyCase): void {
  let current: Record<string, unknown> = document;
  for (const key of testCase.path.slice(0, -1)) {
    const nested = current[key];
    assert.ok(nested !== null && typeof nested === 'object' && !Array.isArray(nested), testCase.name);
    current = nested as Record<string, unknown>;
  }
  const leaf = testCase.path[testCase.path.length - 1];
  if (testCase.delete === true) {
    delete current[leaf];
  } else {
    current[leaf] = testCase.value;
  }
}

for (const testCase of fixture.malformedTaxonomy) {
  const invalid = clonedTaxonomy();
  mutateAtPath(invalid, testCase);
  assert.throws(
    () => decodeDetectionTaxonomy(invalid),
    (error: unknown) => error instanceof DetectionTaxonomyValidationError
      && error.category === testCase.expectedCategory,
    testCase.name,
  );
}

// This explicit object-level check guards JavaScript's boolean coercion boundary.
const booleanSchema = clonedTaxonomy();
booleanSchema.schemaVersion = true;
assert.throws(() => decodeDetectionTaxonomy(booleanSchema), DetectionTaxonomyValidationError);

const integralJsonNumbers = clonedTaxonomy();
integralJsonNumbers.schemaVersion = 1.0;
(integralJsonNumbers.cocoClasses as Record<string, unknown>).person = 0.0;
const normalizedIntegralTaxonomy = decodeDetectionTaxonomy(integralJsonNumbers);
assert.equal(normalizedIntegralTaxonomy.schemaVersion, 1);
assert.equal(normalizedIntegralTaxonomy.cocoClasses.person, 0);

for (const value of [true, 1.5, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1]) {
  const invalid = clonedTaxonomy();
  invalid.schemaVersion = value;
  assert.throws(() => decodeDetectionTaxonomy(invalid), DetectionTaxonomyValidationError, `schemaVersion rejects ${String(value)}`);
}

for (const value of [true, 0.5, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1]) {
  const invalid = clonedTaxonomy();
  (invalid.cocoClasses as Record<string, unknown>).person = value;
  assert.throws(() => decodeDetectionTaxonomy(invalid), DetectionTaxonomyValidationError, `COCO ID rejects ${String(value)}`);
}

const normalizedSampleCount = parseRegistryLabelInput({
  vietnameseName: 'Xe tải',
  baseClass: 'truck',
  sampleCount: 0.0,
});
assert.equal(normalizedSampleCount.sampleCount, 0);

assert.ok(Object.isFrozen(DETECTION_TAXONOMY));
assert.ok(Object.isFrozen(DETECTION_TAXONOMY.cocoClasses));
assert.ok(Object.isFrozen(DETECTION_TAXONOMY.legacyNameConstraints));
assert.ok(Object.isFrozen(DETECTION_TAXONOMY.legacyNameConstraints['xe nâng']));
assert.throws(() => {
  (DETECTION_TAXONOMY.cocoClasses as Record<string, number>).person = 79;
}, TypeError);
assert.throws(() => {
  (DETECTION_TAXONOMY.legacyNameConstraints['xe nâng'] as string[]).push('truck');
}, TypeError);

console.log(`detection taxonomy: PASS (${fixture.cases.length} parity cases, ${fixture.malformedInputs.length + fixture.malformedTaxonomy.length} malformed cases)`);
