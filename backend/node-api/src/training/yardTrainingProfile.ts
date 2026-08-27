import { createHash } from 'crypto';
import fs from 'fs';
import path from 'path';

export const YARD_TRAINING_PROFILE = 'YARD_CUSTOM_V2' as const;
export type TrainingProfileName = typeof YARD_TRAINING_PROFILE;
export type DatasetSplit = 'train' | 'val' | 'test';

export const BAIKIEM_V9_PROFILE = 'BAIKIEM_V9_UNIFIED' as const;
export const BAIKIEM_V9_CLASSES = [
  'person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck',
  'container_truck', 'forklift', 'reach_stacker', 'mobile_crane',
] as const;

export type BaikiemV9Class = typeof BAIKIEM_V9_CLASSES[number];
export type BaikiemV9Profile = {
  schemaVersion: 1;
  profile: typeof BAIKIEM_V9_PROFILE;
  runtimeMode: 'UNIFIED';
  classes: Array<{
    id: number;
    baseClass: BaikiemV9Class;
    recommendedDisplayName: string;
    minimumInstances: number;
    minimumSources: number;
  }>;
  acceptance: { minimumEndToEndFps: number } & Record<string, number>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function loadBaikiemV9Profile(): BaikiemV9Profile {
  const profilePath = path.resolve(__dirname, '../../../config/baikiem-v9-profile.json');
  const parsed: unknown = JSON.parse(fs.readFileSync(profilePath, 'utf8'));
  if (!isRecord(parsed) || parsed.schemaVersion !== 1 || parsed.profile !== BAIKIEM_V9_PROFILE
    || parsed.runtimeMode !== 'UNIFIED' || !Array.isArray(parsed.classes) || !isRecord(parsed.acceptance)) {
    throw new Error('Invalid BAI-KIEM V9 profile');
  }
  const classes = parsed.classes;
  if (classes.length !== BAIKIEM_V9_CLASSES.length) {
    throw new Error('BAI-KIEM V9 profile must contain exactly ten classes');
  }
  classes.forEach((rawClass, index) => {
    if (!isRecord(rawClass) || rawClass.id !== index || rawClass.baseClass !== BAIKIEM_V9_CLASSES[index]
      || typeof rawClass.recommendedDisplayName !== 'string' || !rawClass.recommendedDisplayName.trim()
      || !Number.isSafeInteger(rawClass.minimumInstances) || Number(rawClass.minimumInstances) <= 0
      || !Number.isSafeInteger(rawClass.minimumSources) || Number(rawClass.minimumSources) <= 0) {
      throw new Error(`Invalid BAI-KIEM V9 class definition at index ${index}`);
    }
  });
  if (typeof parsed.acceptance.minimumEndToEndFps !== 'number'
    || !Number.isFinite(parsed.acceptance.minimumEndToEndFps)
    || parsed.acceptance.minimumEndToEndFps !== 8.0) {
    throw new Error('Invalid BAI-KIEM V9 FPS gate');
  }
  return parsed as BaikiemV9Profile;
}

export type ProfileSample = {
  label: string;
  baseClass: string;
  sourceId: string;
  split: DatasetSplit;
};

type LabelRequirement = { label: string; baseClass: string; minimumSamples: number; minimumSources: number };

export const YARD_CUSTOM_LABELS: readonly LabelRequirement[] = [
  { label: 'Xe nâng container', baseClass: 'reach_stacker', minimumSamples: 60, minimumSources: 5 },
];

export const isYardTrainingProfile = (value: unknown): value is TrainingProfileName => value === YARD_TRAINING_PROFILE;

export function isYardTrainingSample(sample: Pick<ProfileSample, 'label' | 'baseClass'>): boolean {
  return YARD_CUSTOM_LABELS.some((required) => required.label === sample.label && required.baseClass === sample.baseClass);
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
  const labelCoverage = YARD_CUSTOM_LABELS.map((required) => {
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
  return { profile: YARD_TRAINING_PROFILE, requiredLabels: YARD_CUSTOM_LABELS, labelCoverage, ready: issues.length === 0, issues };
}
