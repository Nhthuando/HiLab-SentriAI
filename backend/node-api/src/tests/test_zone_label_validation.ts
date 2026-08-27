import assert from 'node:assert/strict';
import type { DetectionCapability } from '../detection/taxonomy';
import {
  validateDetectableTargetLabels,
  ZoneLabelValidationError,
} from '../detection/zoneLabelValidation';

function capability(isDetectable: boolean): DetectionCapability {
  return {
    canonicalClass: isDetectable ? 'person' : 'reach_stacker',
    detectionSource: isDetectable ? 'COCO' : 'UNAVAILABLE',
    isDetectable,
    activeModelVersion: null,
    reasonCode: isDetectable ? 'COCO_BASE_CLASS' : 'NO_ACTIVE_CUSTOM_MODEL',
    reasonText: isDetectable ? 'Detected by COCO' : 'No detection model',
  };
}

const registry = new Map<string, DetectionCapability>([
  ['Person', capability(true)],
  ['Reach stacker', capability(false)],
]);

assert.deepEqual(
  validateDetectableTargetLabels([' person ', 'PERSON'], registry),
  ['Person'],
  'case-insensitive duplicates must return the database display name once',
);
assert.deepEqual(validateDetectableTargetLabels([], registry), []);

const ambiguousRegistry = new Map<string, DetectionCapability>([
  ['Xe tải', capability(true)],
  [' xe tải ', capability(true)],
]);
assert.throws(
  () => validateDetectableTargetLabels(['Xe tải'], ambiguousRegistry),
  (error: unknown) => error instanceof ZoneLabelValidationError
    && error.reasonCode === 'LABEL_AMBIGUOUS'
    && error.rejectedDisplayName === ' xe tải '
    && error.message.includes('Xe tải'),
  'normalized duplicate registry names must be returned as a controlled policy error',
);

assert.throws(
  () => validateDetectableTargetLabels(['Truck'], registry),
  (error: unknown) => error instanceof ZoneLabelValidationError
    && error.reasonCode === 'LABEL_NOT_REGISTERED'
    && error.message.includes('Truck'),
);
assert.throws(
  () => validateDetectableTargetLabels(['reach stacker'], registry),
  (error: unknown) => error instanceof ZoneLabelValidationError
    && error.reasonCode === 'LABEL_NOT_DETECTABLE'
    && error.message.includes('Reach stacker'),
);

console.log('Zone label capability validation checks passed');
