import { createHash, randomUUID } from 'crypto';
import { createReadStream, promises as fs } from 'fs';
import path from 'path';
import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../prisma/client';
import { sendCreated, sendSuccess } from '../utils/response';
import { assignYardSplits, isYardTrainingProfile, isYardTrainingSample, YARD_TRAINING_PROFILE, yardReadiness, type DatasetSplit, type TrainingProfileName } from '../training/yardTrainingProfile';

const trainingDatasetsRouter = Router();
const backendRoot = path.resolve(process.cwd(), '..');
const trainingRoot = path.join(backendRoot, 'data', 'training', 'datasets');
const uploadsRoot = path.join(backendRoot, 'data', 'uploads');
const mediaRegistryPath = path.join(backendRoot, 'data', 'user_media.json');

type MediaRegistryItem = { id: string; kind: 'img' | 'video'; filename: string };
type ManifestSample = {
  sampleId: string;
  label: string;
  baseClass: string;
  sourceId: string;
  mediaKind: 'IMAGE' | 'VIDEO';
  frameTimestampMs: number | null;
  bbox: { x: number; y: number; w: number; h: number };
  mediaPath: string;
  mediaSha256: string;
  split: DatasetSplit;
};
type ResolvedSample = Omit<ManifestSample, 'mediaPath' | 'mediaSha256'> & { sourcePath: string };

async function loadMediaRegistry(): Promise<Map<string, MediaRegistryItem>> {
  try {
    const records = JSON.parse(await fs.readFile(mediaRegistryPath, 'utf8'));
    return new Map(Array.isArray(records) ? records.map((record) => [record.id, record]) : []);
  } catch {
    return new Map();
  }
}

async function sha256File(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    const stream = createReadStream(filePath);
    stream.on('error', reject);
    stream.on('data', (chunk: string | Buffer) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

async function collectSamples(profile?: TrainingProfileName): Promise<{ samples: ResolvedSample[]; excluded: Array<{ id: string; reason: string }>; ignoredSamples: number }> {
  const records = await prisma.labelSample.findMany({
    include: { label: { select: { vietnameseName: true, baseClass: true } } },
    orderBy: { createdAt: 'asc' },
  });
  const mediaById = await loadMediaRegistry();
  const samples: ResolvedSample[] = [];
  const excluded: Array<{ id: string; reason: string }> = [];

  for (const record of records) {
    const bbox = record.bbox as any;
    const validBox = bbox && [bbox.x, bbox.y, bbox.w, bbox.h].every(Number.isFinite)
      && bbox.x >= 0 && bbox.y >= 0 && bbox.w > 0 && bbox.h > 0 && bbox.x + bbox.w <= 1 && bbox.y + bbox.h <= 1;
    const media = record.mediaRef ? mediaById.get(record.mediaRef) : undefined;
    const mediaKind = media?.kind === 'video' ? 'VIDEO' : media?.kind === 'img' ? 'IMAGE' : null;
    const filename = media?.filename ? path.basename(media.filename) : '';
    const sourcePath = path.resolve(uploadsRoot, filename);
    const relativePath = path.relative(uploadsRoot, sourcePath);
    const safeSourcePath = Boolean(filename) && Boolean(relativePath) && !relativePath.startsWith('..') && !path.isAbsolute(relativePath);
    const frameValid = mediaKind === 'VIDEO'
      ? record.frameTimestampMs != null && record.frameTimestampMs >= 0
      : record.frameTimestampMs == null;

    if (!record.mediaRef || !mediaKind || !safeSourcePath || !validBox || !frameValid) {
      excluded.push({ id: record.id, reason: !record.mediaRef || !mediaKind || !safeSourcePath ? 'Thiếu nguồn ảnh/video đã lưu' : !frameValid ? 'Thời điểm khung video không hợp lệ' : 'Khung đánh dấu không hợp lệ' });
      continue;
    }
    try {
      if (!(await fs.stat(sourcePath)).isFile()) throw new Error('not a file');
    } catch {
      excluded.push({ id: record.id, reason: 'File ảnh/video gốc không còn tồn tại' });
      continue;
    }
    samples.push({
      sampleId: record.id,
      label: record.label.vietnameseName,
      baseClass: record.label.baseClass,
      sourceId: record.mediaRef,
      mediaKind,
      frameTimestampMs: record.frameTimestampMs,
      bbox,
      sourcePath,
      split: 'train',
    });
  }
  const selected = profile === YARD_TRAINING_PROFILE ? samples.filter((sample) => isYardTrainingSample(sample)) : samples;
  // A source must live in exactly one split. Select at least one validation
  // source deterministically so adjacent frames cannot leak into validation.
  const sourceIds = [...new Set(selected.map((sample) => sample.sourceId))]
    .sort((left, right) => createHash('sha256').update(left).digest('hex').localeCompare(createHash('sha256').update(right).digest('hex')));
  const validationSources = new Set(sourceIds.slice(0, Math.max(1, Math.ceil(sourceIds.length / 5))));
  selected.forEach((sample) => { sample.split = validationSources.has(sample.sourceId) ? 'val' : 'train'; });
  return {
    samples: profile === YARD_TRAINING_PROFILE ? assignYardSplits(selected) : selected,
    excluded,
    ignoredSamples: samples.length - selected.length,
  };
}

function readiness(samples: ResolvedSample[], excluded: Array<{ id: string; reason: string }>, profile?: TrainingProfileName, ignoredSamples = 0) {
  const labels = new Set(samples.map((sample) => sample.label));
  const yard = profile === YARD_TRAINING_PROFILE ? yardReadiness(samples) : null;
  return {
    savedSamples: samples.length,
    labelsWithSamples: labels.size,
    sourceCount: new Set(samples.map((sample) => sample.sourceId)).size,
    excludedSamples: excluded.length,
    ignoredSamples,
    profile: yard?.profile || null,
    labelCoverage: yard?.labelCoverage || [],
    issues: yard?.issues || [],
    ready: yard?.ready ?? (samples.length >= 20 && labels.size >= 1 && new Set(samples.map((sample) => sample.sourceId)).size >= 3),
    excluded,
  };
}

function requestedProfile(value: unknown): TrainingProfileName | undefined {
  if (value == null || value === '') return undefined;
  if (!isYardTrainingProfile(value)) throw new Error('Training profile không được hỗ trợ');
  return value;
}

trainingDatasetsRouter.get('/readiness', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const profile = requestedProfile(req.query.profile);
    const { samples, excluded, ignoredSamples } = await collectSamples(profile);
    return sendSuccess(res, readiness(samples, excluded, profile, ignoredSamples));
  } catch (error) { return next(error); }
});

trainingDatasetsRouter.post('/export', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const profile = requestedProfile(req.body?.profile);
    const { samples, excluded, ignoredSamples } = await collectSamples(profile);
    const state = readiness(samples, excluded, profile, ignoredSamples);
    if (!state.ready) return sendSuccess(res, { exported: false, reason: 'Cần ít nhất 20 mẫu hợp lệ từ 3 ảnh/video khác nhau trước khi xuất dataset', ...state });

    const sourceHashes = new Map<string, string>();
    for (const sample of samples) {
      if (!sourceHashes.has(sample.sourceId)) sourceHashes.set(sample.sourceId, await sha256File(sample.sourcePath));
    }
    const frozenSamples: ManifestSample[] = samples.map((sample) => {
      const mediaSha256 = sourceHashes.get(sample.sourceId)!;
      const extension = path.extname(sample.sourcePath).toLowerCase() || (sample.mediaKind === 'VIDEO' ? '.mp4' : '.jpg');
      return {
        sampleId: sample.sampleId,
        label: sample.label,
        baseClass: sample.baseClass,
        sourceId: sample.sourceId,
        mediaKind: sample.mediaKind,
        frameTimestampMs: sample.frameTimestampMs,
        bbox: sample.bbox,
        mediaPath: `media/${mediaSha256}${extension}`,
        mediaSha256,
        split: sample.split,
      };
    });
    const snapshot = { schemaVersion: 2, profile: profile || null, samples: frozenSamples };
    const contentHash = createHash('sha256').update(JSON.stringify(snapshot)).digest('hex');
    const existing = await prisma.trainingDataset.findUnique({ where: { contentHash } });
    if (existing) return sendSuccess(res, { exported: true, reused: true, dataset: existing, excluded });

    const id = randomUUID();
    const directory = path.join(trainingRoot, id);
    await fs.mkdir(directory, { recursive: true });
    const frozenBySample = new Map(frozenSamples.map((sample) => [sample.sampleId, sample]));
    for (const sample of samples) {
      const target = path.join(directory, frozenBySample.get(sample.sampleId)!.mediaPath);
      await fs.mkdir(path.dirname(target), { recursive: true });
      try { await fs.access(target); } catch { await fs.copyFile(sample.sourcePath, target); }
    }
    await fs.writeFile(path.join(directory, 'manifest.json'), JSON.stringify({ ...snapshot, contentHash, createdAt: new Date().toISOString(), excluded, ignoredSamples }, null, 2), 'utf8');
    const dataset = await prisma.trainingDataset.create({
      data: {
        id,
        manifestPath: path.relative(backendRoot, path.join(directory, 'manifest.json')).replace(/\\/g, '/'),
        contentHash,
        sampleCount: samples.length,
        sourceCount: new Set(samples.map((sample) => sample.sourceId)).size,
      },
    });
    return sendCreated(res, { exported: true, reused: false, dataset, excluded });
  } catch (error) { return next(error); }
});

export { trainingDatasetsRouter };
