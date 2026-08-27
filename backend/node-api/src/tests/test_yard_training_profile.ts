import assert from 'assert';
import {
  assignYardSplits,
  isYardTrainingProfile,
  isYardTrainingSample,
  YARD_TRAINING_PROFILE,
  yardReadiness,
} from '../training/yardTrainingProfile';

const samples = Array.from({ length: 60 }, (_, index) => ({
  label: 'Xe nâng container',
  baseClass: 'reach_stacker',
  sourceId: `source-${index % 8}`,
  split: 'train' as const,
}));

const ready = yardReadiness(assignYardSplits(samples));
assert.equal(ready.ready, true);
assert.equal(ready.profile, 'YARD_CUSTOM_V2');
assert.equal(ready.labelCoverage.length, 1);
assert.equal(ready.labelCoverage[0].baseClass, 'reach_stacker');
assert.equal(ready.labelCoverage.every((item) => item.splitCounts.test >= 6 && item.splitCounts.val >= 6), true);
assert.equal(isYardTrainingProfile(YARD_TRAINING_PROFILE), true);
assert.equal(isYardTrainingProfile('YARD_VEHICLE_V1'), false);
assert.equal(isYardTrainingSample(samples[0]), true);
assert.equal(isYardTrainingSample({ label: 'Xe tải', baseClass: 'truck' }), false);

const incomplete = yardReadiness(assignYardSplits(samples.slice(0, 59)));
assert.equal(incomplete.ready, false);
assert.equal(incomplete.labelCoverage[0].ready, false);

console.log('yard training profile: PASS');
