import fs from 'fs';
import path from 'path';

export type DetectionSource = 'COCO' | 'CUSTOM' | 'UNAVAILABLE';
export type RuntimeMode = 'SUPPLEMENTAL' | 'UNIFIED';

export interface RegistryLabelInput {
  vietnameseName: string;
  baseClass: string;
  sampleCount?: number;
}

/**
 * The only registry fields allowed to influence runtime detection routing.
 * `sampleCount` belongs to the label-management DTO and is deliberately
 * absent here: training readiness must not change a label's detector source.
 */
export interface CapabilityLabelInput {
  vietnameseName: string;
  baseClass: string;
}

export interface ActiveModelInput {
  versionKey: string;
  labelMap: Record<string, string>;
  runtimeMode: RuntimeMode;
}

export interface DetectionCapability {
  canonicalClass: string | null;
  detectionSource: DetectionSource;
  isDetectable: boolean;
  activeModelVersion: string | null;
  reasonCode: string;
  reasonText: string;
}

export interface DetectionTaxonomy {
  readonly schemaVersion: 1;
  readonly cocoClasses: Readonly<Record<string, number>>;
  readonly syntaxAliases: Readonly<Record<string, string>>;
  readonly recommendedDisplayNames: Readonly<Record<string, string>>;
  readonly legacyNameConstraints: Readonly<Record<string, readonly string[]>>;
}

/** Shared category exposed by malformed config failures in both runtimes. */
export class DetectionTaxonomyValidationError extends Error {
  readonly category = 'TAXONOMY_VALIDATION' as const;

  constructor(message: string) {
    super(message);
    this.name = 'DetectionTaxonomyValidationError';
  }
}

/** Shared category exposed by malformed resolver DTO failures in both runtimes. */
export class DetectionInputValidationError extends Error {
  readonly category = 'INPUT_VALIDATION' as const;

  constructor(message: string) {
    super(message);
    this.name = 'DetectionInputValidationError';
  }
}

const CANONICAL_CLASS_PATTERN = /^[a-z][a-z0-9_]{1,49}$/;
// Intentional explicit Unicode whitespace policy. U+001C FILE SEPARATOR is not
// whitespace here because Python and JavaScript disagree about it by default.
const SHARED_WHITESPACE = /[\u0009-\u000D\u0020\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+/gu;
const NORMALIZED_SHARED_WHITESPACE_AT_EDGES = /^ +| +$/gu;
const TAXONOMY_PATH = path.resolve(__dirname, '../../../config/detection-taxonomy.json');

const EXPECTED_COCO_CLASSES: Readonly<Record<string, number>> = Object.freeze({
  person: 0,
  bicycle: 1,
  car: 2,
  motorcycle: 3,
  bus: 5,
  truck: 7,
});

const EXPECTED_SYNTAX_ALIASES: Readonly<Record<string, string>> = Object.freeze({
  'reach stacker': 'reach_stacker',
  'reach-stacker': 'reach_stacker',
  'container truck': 'container_truck',
  'container-truck': 'container_truck',
  'mobile crane': 'mobile_crane',
  'shipping container': 'shipping_container',
});

const EXPECTED_LEGACY_NAME_CONSTRAINTS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  container: Object.freeze([]),
  'xe nâng': Object.freeze(['reach_stacker', 'forklift']),
  'xe cẩu': Object.freeze(['mobile_crane']),
});

const EXPECTED_RECOMMENDED_DISPLAY_NAMES: Readonly<Record<string, string>> = Object.freeze({
  person: 'Người',
  bicycle: 'Xe đạp',
  car: 'Xe con',
  motorcycle: 'Xe máy',
  bus: 'Xe buýt',
  truck: 'Xe tải',
  reach_stacker: 'Xe nâng container',
  container_truck: 'Xe đầu kéo container',
  forklift: 'Xe nâng hàng',
  mobile_crane: 'Xe cẩu tự hành',
  shipping_container: 'Container tĩnh',
});

const KNOWN_SUPPORTED_CLASSES = Object.freeze([
  ...Object.keys(EXPECTED_COCO_CLASSES),
  'reach_stacker',
  'container_truck',
  'forklift',
  'mobile_crane',
  'shipping_container',
]);

function parseFiniteSafeInteger(value: unknown, field: string, failure: (message: string) => never): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || !Number.isSafeInteger(value)) {
    failure(`Invalid finite safe integer at ${field}`);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function taxonomyError(message: string): never {
  throw new DetectionTaxonomyValidationError(message);
}

function inputError(message: string): never {
  throw new DetectionInputValidationError(message);
}

function validateCanonicalClass(value: unknown, field: string): string {
  if (typeof value !== 'string' || value === 'container' || !CANONICAL_CLASS_PATTERN.test(value)) {
    taxonomyError(`Invalid canonical class at ${field}`);
  }
  return value;
}

function assertExactKeys(
  actual: Record<string, unknown>,
  expected: Readonly<Record<string, unknown>>,
  section: string,
): void {
  const actualKeys = Object.keys(actual).sort();
  const expectedKeys = Object.keys(expected).sort();
  if (actualKeys.length !== expectedKeys.length || actualKeys.some((key, index) => key !== expectedKeys[index])) {
    taxonomyError(`Invalid required keys at ${section}`);
  }
}

function assertExactStringRecord(
  value: unknown,
  expected: Readonly<Record<string, string>>,
  section: string,
): Record<string, string> {
  if (!isRecord(value)) {
    taxonomyError(`Invalid detection taxonomy section: ${section}`);
  }
  assertExactKeys(value, expected, section);
  const result: Record<string, string> = {};
  for (const [key, expectedValue] of Object.entries(expected)) {
    if (value[key] !== expectedValue) {
      taxonomyError(`Invalid required mapping at ${section}.${key}`);
    }
    result[key] = expectedValue;
  }
  return result;
}

function validateNonblankString(value: unknown, field: string, failure: (message: string) => never): string {
  if (typeof value !== 'string' || normalizedText(value).length === 0) {
    failure(`Invalid nonblank string at ${field}`);
  }
  return value;
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const nestedValue of Object.values(value as Record<string, unknown>)) {
      deepFreeze(nestedValue);
    }
    Object.freeze(value);
  }
  return value;
}

/** Decode and exhaustively validate the versioned shared taxonomy. */
export function decodeDetectionTaxonomy(parsed: unknown): DetectionTaxonomy {
  if (!isRecord(parsed)) {
    taxonomyError('Unsupported detection taxonomy schema');
  }
  const schemaVersion = parseFiniteSafeInteger(parsed.schemaVersion, 'schemaVersion', taxonomyError);
  if (schemaVersion !== 1) {
    taxonomyError('Unsupported detection taxonomy schema');
  }

  const cocoRaw = parsed.cocoClasses;
  if (!isRecord(cocoRaw)) {
    taxonomyError('Invalid detection taxonomy section: cocoClasses');
  }
  assertExactKeys(cocoRaw, EXPECTED_COCO_CLASSES, 'cocoClasses');
  const cocoClasses: Record<string, number> = {};
  const cocoIds = new Set<number>();
  for (const [canonicalClass, expectedId] of Object.entries(EXPECTED_COCO_CLASSES)) {
    const value = parseFiniteSafeInteger(cocoRaw[canonicalClass], `cocoClasses.${canonicalClass}`, taxonomyError);
    validateCanonicalClass(canonicalClass, `cocoClasses.${canonicalClass}`);
    if (value !== expectedId || cocoIds.has(value)) {
      taxonomyError(`Invalid required COCO mapping at cocoClasses.${canonicalClass}`);
    }
    cocoIds.add(value);
    cocoClasses[canonicalClass] = value;
  }

  const syntaxAliases = assertExactStringRecord(
    parsed.syntaxAliases,
    EXPECTED_SYNTAX_ALIASES,
    'syntaxAliases',
  );
  for (const [alias, target] of Object.entries(syntaxAliases)) {
    if (normalizedKey(alias) !== alias || validateCanonicalClass(target, `syntaxAliases.${alias}`) !== target) {
      taxonomyError(`Invalid required mapping at syntaxAliases.${alias}`);
    }
  }

  const recommendedDisplayNames = assertExactStringRecord(
    parsed.recommendedDisplayNames,
    EXPECTED_RECOMMENDED_DISPLAY_NAMES,
    'recommendedDisplayNames',
  );
  for (const canonicalClass of KNOWN_SUPPORTED_CLASSES) {
    validateCanonicalClass(canonicalClass, `recommendedDisplayNames.${canonicalClass}`);
  }

  const constraintsRaw = parsed.legacyNameConstraints;
  if (!isRecord(constraintsRaw)) {
    taxonomyError('Invalid detection taxonomy section: legacyNameConstraints');
  }
  assertExactKeys(constraintsRaw, EXPECTED_LEGACY_NAME_CONSTRAINTS, 'legacyNameConstraints');
  const legacyNameConstraints: Record<string, string[]> = {};
  for (const [legacyName, expectedClasses] of Object.entries(EXPECTED_LEGACY_NAME_CONSTRAINTS)) {
    const allowedClasses = constraintsRaw[legacyName];
    if (!Array.isArray(allowedClasses) || allowedClasses.length !== expectedClasses.length) {
      taxonomyError(`Invalid required mapping at legacyNameConstraints.${legacyName}`);
    }
    for (let index = 0; index < expectedClasses.length; index += 1) {
      if (allowedClasses[index] !== expectedClasses[index]) {
        taxonomyError(`Invalid required mapping at legacyNameConstraints.${legacyName}`);
      }
    }
    legacyNameConstraints[legacyName] = [...expectedClasses];
  }

  return deepFreeze({
    schemaVersion: 1,
    cocoClasses,
    syntaxAliases,
    recommendedDisplayNames,
    legacyNameConstraints,
  });
}

function loadTaxonomy(taxonomyPath = TAXONOMY_PATH): DetectionTaxonomy {
  return decodeDetectionTaxonomy(JSON.parse(fs.readFileSync(taxonomyPath, 'utf8')) as unknown);
}

export const DETECTION_TAXONOMY: DetectionTaxonomy = loadTaxonomy();

/**
 * Every recommended display name is reserved for its exact canonical class.
 * This reverse map is derived from the shared taxonomy rather than maintained
 * as a second hand-written list.
 */
const RESERVED_DISPLAY_NAME_TO_CANONICAL_CLASS: ReadonlyMap<string, string> = new Map(
  Object.entries(DETECTION_TAXONOMY.recommendedDisplayNames)
    .map(([canonicalClass, displayName]) => [normalizeDisplayNameKey(displayName), canonicalClass]),
);

/** Normalize equivalent Unicode spellings consistently with Python. */
function normalizedText(value: string): string {
  // Native end trimming has a different Unicode definition across runtimes,
  // notably around U+001C. The preceding replacement
  // turns only approved whitespace into ASCII spaces, which we then remove.
  return value.normalize('NFC').replace(/\uFEFF/gu, '').replace(SHARED_WHITESPACE, ' ').replace(NORMALIZED_SHARED_WHITESPACE_AT_EDGES, '');
}

function normalizedKey(value: string): string {
  return normalizedText(value).toLowerCase();
}

/**
 * Shared display-name normalization for consumers which need a stable lookup
 * key. It intentionally applies syntax-only Unicode/whitespace normalization,
 * not a semantic label alias.
 */
export function normalizeDisplayNameKey(value: string): string {
  return normalizedKey(value);
}

function assertExactDtoKeys(value: Record<string, unknown>, allowedKeys: readonly string[], typeName: string): void {
  const keys = Object.keys(value).sort();
  const expected = [...allowedKeys].sort();
  if (keys.length !== expected.length || keys.some((key, index) => key !== expected[index])) {
    inputError(`Invalid ${typeName} fields`);
  }
}

function requireDtoString(value: Record<string, unknown>, field: string, typeName: string): string {
  return validateNonblankString(value[field], `${typeName}.${field}`, inputError);
}

/** Strictly decode a registry label DTO; no coercion or unknown fields are accepted. */
export function parseRegistryLabelInput(value: unknown): RegistryLabelInput {
  if (!isRecord(value)) {
    inputError('Invalid RegistryLabelInput');
  }
  const hasSampleCount = Object.prototype.hasOwnProperty.call(value, 'sampleCount');
  assertExactDtoKeys(value, hasSampleCount
    ? ['vietnameseName', 'baseClass', 'sampleCount']
    : ['vietnameseName', 'baseClass'], 'RegistryLabelInput');
  const sampleCount = value.sampleCount;
  const parsedSampleCount = hasSampleCount
    ? parseFiniteSafeInteger(sampleCount, 'RegistryLabelInput.sampleCount', inputError)
    : undefined;
  if (parsedSampleCount !== undefined && parsedSampleCount < 0) {
    inputError('Invalid RegistryLabelInput.sampleCount');
  }
  return hasSampleCount
    ? {
      vietnameseName: requireDtoString(value, 'vietnameseName', 'RegistryLabelInput'),
      baseClass: requireDtoString(value, 'baseClass', 'RegistryLabelInput'),
      sampleCount: parsedSampleCount,
    }
    : {
      vietnameseName: requireDtoString(value, 'vietnameseName', 'RegistryLabelInput'),
      baseClass: requireDtoString(value, 'baseClass', 'RegistryLabelInput'),
    };
}

/**
 * Decode only the two fields that are meaningful to runtime routing. Extra
 * DTO/display fields (including malformed sample counts) are intentionally
 * ignored here, because they must never alter a capability decision.
 */
function parseCapabilityLabelInput(value: unknown): CapabilityLabelInput {
  if (!isRecord(value)) {
    inputError('Invalid CapabilityLabelInput');
  }
  return {
    vietnameseName: requireDtoString(value, 'vietnameseName', 'CapabilityLabelInput'),
    baseClass: requireDtoString(value, 'baseClass', 'CapabilityLabelInput'),
  };
}

/** Strictly decode an active-model DTO; every labelMap key and value must be nonblank. */
export function parseActiveModelInput(value: unknown): ActiveModelInput {
  if (!isRecord(value)) {
    inputError('Invalid ActiveModelInput');
  }
  const hasRuntimeMode = Object.prototype.hasOwnProperty.call(value, 'runtimeMode');
  assertExactDtoKeys(
    value,
    hasRuntimeMode ? ['versionKey', 'labelMap', 'runtimeMode'] : ['versionKey', 'labelMap'],
    'ActiveModelInput',
  );
  if (!isRecord(value.labelMap)) {
    inputError('Invalid ActiveModelInput.labelMap');
  }
  const labelMap: Record<string, string> = {};
  for (const [key, rawClass] of Object.entries(value.labelMap)) {
    const validatedKey = validateNonblankString(key, 'ActiveModelInput.labelMap key', inputError);
    const validatedClass = validateNonblankString(
      rawClass,
      `ActiveModelInput.labelMap.${key}`,
      inputError,
    );
    if (normalizeCanonicalClass(validatedClass) === null) {
      inputError(`Invalid ActiveModelInput.labelMap.${validatedKey} canonical class`);
    }
    labelMap[validatedKey] = validatedClass;
  }
  const runtimeMode = hasRuntimeMode ? value.runtimeMode : 'SUPPLEMENTAL';
  if (runtimeMode !== 'SUPPLEMENTAL' && runtimeMode !== 'UNIFIED') {
    inputError('Invalid ActiveModelInput.runtimeMode');
  }
  return {
    versionKey: requireDtoString(value, 'versionKey', 'ActiveModelInput'),
    labelMap,
    runtimeMode,
  };
}

/** Normalize spelling only; semantic aliases are intentionally not supported. */
export function normalizeCanonicalClass(value: string): string | null {
  const key = normalizedKey(value);
  const candidate = DETECTION_TAXONOMY.syntaxAliases[key] ?? key;
  if (candidate === 'container' || !CANONICAL_CLASS_PATTERN.test(candidate)) {
    return null;
  }
  return candidate;
}

function unavailable(canonicalClass: string | null, reasonCode: string, reasonText: string): DetectionCapability {
  return {
    canonicalClass,
    detectionSource: 'UNAVAILABLE',
    isDetectable: false,
    activeModelVersion: null,
    reasonCode,
    reasonText,
  };
}

function validateRegistryMapping(label: CapabilityLabelInput):
  | { canonicalClass: string; error: null }
  | { canonicalClass: null; error: DetectionCapability } {
  const rawClass = normalizedText(label.baseClass);
  const canonicalClass = normalizeCanonicalClass(rawClass);
  if (normalizedKey(rawClass) === 'container') {
    return { canonicalClass: null, error: unavailable(null, 'AMBIGUOUS_CONTAINER', 'Class container không xác định xe đầu kéo hay container tĩnh') };
  }
  if (canonicalClass === null) {
    return { canonicalClass: null, error: unavailable(null, 'INVALID_CANONICAL_CLASS', `Class ${rawClass} không phải định danh canonical hợp lệ`) };
  }

  const displayName = normalizedText(label.vietnameseName);
  const displayKey = normalizeDisplayNameKey(displayName);
  const reservedCanonicalClass = RESERVED_DISPLAY_NAME_TO_CANONICAL_CLASS.get(displayKey);
  if (reservedCanonicalClass !== undefined && reservedCanonicalClass !== canonicalClass) {
    return {
      canonicalClass: null,
      error: unavailable(
        null,
        'RESERVED_DISPLAY_NAME_CLASS_MISMATCH',
        `Tên ${displayName} phải dùng class ${reservedCanonicalClass}, không phải ${canonicalClass}`,
      ),
    };
  }
  if (Object.prototype.hasOwnProperty.call(DETECTION_TAXONOMY.legacyNameConstraints, displayKey)) {
    const allowedClasses = DETECTION_TAXONOMY.legacyNameConstraints[displayKey];
    if (allowedClasses.length === 0) {
      return { canonicalClass: null, error: unavailable(null, 'AMBIGUOUS_CONTAINER', 'Tên Container không xác định xe đầu kéo hay container tĩnh') };
    }
    if (!allowedClasses.includes(canonicalClass)) {
      return { canonicalClass: null, error: unavailable(null, 'LEGACY_NAME_CLASS_MISMATCH', `Tên ${displayName} không phù hợp với class ${canonicalClass}`) };
    }
  }
  return { canonicalClass, error: null };
}

function activeManifestClasses(activeModel: ActiveModelInput): ReadonlySet<string> {
  const classes = new Set<string>();
  for (const rawClass of Object.values(activeModel.labelMap)) {
    const canonicalClass = normalizeCanonicalClass(rawClass);
    if (canonicalClass !== null) {
      classes.add(canonicalClass);
    }
  }
  return classes;
}

function legacyManifestClass(
  label: CapabilityLabelInput,
  activeModel: ActiveModelInput,
): string | null {
  const displayKey = normalizeDisplayNameKey(label.vietnameseName);
  const allowedClasses = DETECTION_TAXONOMY.legacyNameConstraints[displayKey];
  if (!allowedClasses?.length) return null;
  for (const [modelLabel, rawClass] of Object.entries(activeModel.labelMap)) {
    if (normalizeDisplayNameKey(modelLabel) !== displayKey) continue;
    const canonicalClass = normalizeCanonicalClass(rawClass);
    return canonicalClass !== null && allowedClasses.includes(canonicalClass) ? canonicalClass : null;
  }
  return null;
}

/** Resolve capability only after strict DTO decoding; sample count never affects routing. */
export function resolveLabelCapability(label: unknown, activeModel: unknown | null): DetectionCapability {
  const parsedLabel = parseCapabilityLabelInput(label);
  const parsedActiveModel = activeModel === null ? null : parseActiveModelInput(activeModel);
  const mapping = validateRegistryMapping(parsedLabel);
  if (mapping.error !== null) {
    if (parsedActiveModel !== null && mapping.error.reasonCode === 'LEGACY_NAME_CLASS_MISMATCH') {
      const manifestClass = legacyManifestClass(parsedLabel, parsedActiveModel);
      if (manifestClass !== null) {
        return {
          canonicalClass: manifestClass,
          detectionSource: 'CUSTOM',
          isDetectable: true,
          activeModelVersion: parsedActiveModel.versionKey,
          reasonCode: 'ACTIVE_CUSTOM_LEGACY_LABEL',
          reasonText: `Nhận diện bởi model custom ${parsedActiveModel.versionKey}; nhãn legacy được định nghĩa bởi manifest`,
        };
      }
    }
    return mapping.error;
  }
  const { canonicalClass } = mapping;
  const manifestClasses = parsedActiveModel === null ? new Set<string>() : activeManifestClasses(parsedActiveModel);
  if (parsedActiveModel?.runtimeMode === 'UNIFIED') {
    if (manifestClasses.has(canonicalClass)) {
      return {
        canonicalClass,
        detectionSource: 'CUSTOM',
        isDetectable: true,
        activeModelVersion: parsedActiveModel.versionKey,
        reasonCode: 'ACTIVE_UNIFIED_CLASS',
        reasonText: `Nháº­n diá»‡n bá»Ÿi model unified ${parsedActiveModel.versionKey}`,
      };
    }
    return unavailable(
      canonicalClass,
      'UNIFIED_CLASS_NOT_IN_ACTIVE_MODEL',
      `Model unified Ä‘ang hoáº¡t Ä‘á»™ng khĂ´ng há»— trá»£ class ${canonicalClass}`,
    );
  }
  if (Object.prototype.hasOwnProperty.call(DETECTION_TAXONOMY.cocoClasses, canonicalClass)) {
    return { canonicalClass, detectionSource: 'COCO', isDetectable: true, activeModelVersion: null, reasonCode: 'COCO_BASE_CLASS', reasonText: 'Nhận diện bởi model COCO' };
  }
  if (parsedActiveModel === null) {
    return unavailable(canonicalClass, 'NO_ACTIVE_CUSTOM_MODEL', 'Chưa có model nhận diện');
  }
  if (manifestClasses.has(canonicalClass)) {
    return { canonicalClass, detectionSource: 'CUSTOM', isDetectable: true, activeModelVersion: parsedActiveModel.versionKey, reasonCode: 'ACTIVE_CUSTOM_CLASS', reasonText: `Nhận diện bởi model custom ${parsedActiveModel.versionKey}` };
  }
  return unavailable(canonicalClass, 'CUSTOM_CLASS_NOT_IN_ACTIVE_MODEL', `Model custom đang hoạt động không hỗ trợ class ${canonicalClass}`);
}
