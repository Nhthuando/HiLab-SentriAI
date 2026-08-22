import { createHash } from 'crypto';

export const YARD_TRAINING_PROFILE = 'YARD_VEHICLE_V1' as const;
export type TrainingProfileName = typeof YARD_TRAINING_PROFILE;
export type DatasetSplit = 'train' | 'val' | 'test';

export type ProfileSample = {
  label: string;
  baseClass: string;
  sourceId: string;
  split: DatasetSplit;
};

type LabelRequirement = { label: string; baseClass: string; minimumSamples: number; minimumSources: number };

const YARD_LABELS: readonly LabelRequirement[] = [
  { label: 'Container', baseClass: 'container', minimumSamples: 60, minimumSources: 5 },
  { label: 'Xe tải', baseClass: 'truck', minimumSamples: 60, minimumSources: 5 },
  { label: 'Xe nâng', baseClass: 'forklift', minimumSamples: 60, minimumSources: 5 },
];

export const isYardTrainingProfile = (value: unknown): value is TrainingProfileName => value === YARD_TRAINING_PROFILE;

export function isYardTrainingSample(sample: Pick<ProfileSample, 'label' | 'baseClass'>): boolean {
  return YARD_LABELS.some((required) => required.label === sample.label && required.baseClass === sample.baseClass);
}

/** Keep all frames from one uploaded image/video in one split to avoid leakage. */
export function assignYardSplits<T extends ProfileSample>(samples: T[]): T[] {
  const sourceIds = [...new Set(samples.map((sample) => sample.sourceId))]
    .sort((left, right) => createHash('sha256').update(left).digest('hex').localeCompare(createHash('sha256').update(right).digest('hex')));
  const testCount = Math.max(1, Math.ceil(sourceIds.length / 5));
  const valCount = Math.max(1, Math.ceil(sourceIds.length / 5));
  const testSources = new Set(sourceIds.slice(0, testCount));
  const valSources = new Set(sourceIds.slice(testCount, testCount + valCount));
  return samples.map((sample) => ({
    ...sample,
    split: testSources.has(sample.sourceId) ? 'test' : valSources.has(sample.sourceId) ? 'val' : 'train',
  }));
}

export function yardReadiness(samples: ProfileSample[]) {
  const labelCoverage = YARD_LABELS.map((required) => {
    const matching = samples.filter((sample) => sample.label === required.label && sample.baseClass === required.baseClass);
    const splitCounts = {
      train: matching.filter((sample) => sample.split === 'train').length,
      val: matching.filter((sample) => sample.split === 'val').length,
      test: matching.filter((sample) => sample.split === 'test').length,
    };
    return {
      ...required,
      savedSamples: matching.length,
      sourceCount: new Set(matching.map((sample) => sample.sourceId)).size,
      splitCounts,
      ready: matching.length >= required.minimumSamples
        && new Set(matching.map((sample) => sample.sourceId)).size >= required.minimumSources
        && splitCounts.train >= 30 && splitCounts.val >= 6 && splitCounts.test >= 6,
    };
  });
  const sourceCount = new Set(samples.map((sample) => sample.sourceId)).size;
  const issues = [
    ...(sourceCount < 5 ? ['Cần mẫu từ ít nhất 5 ảnh/video khác nhau để tách train, kiểm tra và đánh giá độc lập.'] : []),
    ...labelCoverage.filter((entry) => !entry.ready).map((entry) =>
      `${entry.label}: cần ít nhất ${entry.minimumSamples} ô từ ${entry.minimumSources} nguồn; split hiện có train/val/test là ${entry.splitCounts.train}/${entry.splitCounts.val}/${entry.splitCounts.test}.`),
  ];
  return { profile: YARD_TRAINING_PROFILE, requiredLabels: YARD_LABELS, labelCoverage, ready: issues.length === 0, issues };
}
