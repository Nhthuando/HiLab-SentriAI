import assert from 'assert';
import { assignYardSplits, yardReadiness } from '../training/yardTrainingProfile';

const labels = ['Container', 'Xe tải', 'Xe nâng'] as const;
const baseClasses = ['container', 'truck', 'forklift'] as const;
const samples = labels.flatMap((label, labelIndex) => Array.from({ length: 60 }, (_, index) => ({
  label,
  baseClass: baseClasses[labelIndex],
  sourceId: `source-${index % 8}`,
  split: 'train' as const,
})));

const ready = yardReadiness(assignYardSplits(samples));
assert.equal(ready.ready, true);
assert.equal(ready.labelCoverage.length, 3);
assert.equal(ready.labelCoverage.every((item) => item.splitCounts.test >= 6 && item.splitCounts.val >= 6), true);

const incomplete = yardReadiness(assignYardSplits(samples.filter((sample) => sample.label !== 'Container')));
assert.equal(incomplete.ready, false);
assert.equal(incomplete.labelCoverage.find((item) => item.label === 'Container')?.ready, false);

console.log('yard training profile: PASS');
