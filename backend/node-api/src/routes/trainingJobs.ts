import { createHash } from 'crypto';
import { spawn } from 'child_process';
import { createReadStream, existsSync, readdirSync, readFileSync } from 'fs';
import path from 'path';
import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../prisma/client';
import { BadRequestError, NotFoundError } from '../utils/errors';
import { sendCreated, sendSuccess } from '../utils/response';

const trainingJobsRouter = Router();
const backendRoot = path.resolve(process.cwd(), '..');
const workerRoot = path.join(backendRoot, 'python-worker');
const dataRoot = path.join(backendRoot, 'data');
const trainingRoot = path.join(dataRoot, 'training');
const runnerReportsRoot = path.join(trainingRoot, 'reports');
const python = path.join(workerRoot, '.venv', 'Scripts', 'python.exe');
// Keep every supported checkpoint explicit.  A requested model is still
// resolved under python-worker/models, so callers cannot execute arbitrary
// paths through the training worker.
const allowedBaseModels = new Set(['yolov8n.pt', 'yolo11n.pt']);
const retryTimers = new Map<string, NodeJS.Timeout>();

type RunnerEvent = {
  event: string;
  epoch?: number;
  totalEpochs?: number;
  outcome?: 'paused' | 'completed';
  reason?: string;
  artifactPath?: string;
  artifactSha256?: string;
  metrics?: unknown;
  labelMap?: Record<string, string>;
  accepted?: boolean;
};

function safeReason(reason: unknown): string {
  return String(reason || 'Training runner stopped').replace(/[\r\n]/g, ' ').slice(0, 200);
}

function runnerFailureReason(stderr: string): string {
  const lines = stderr.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const specific = [...lines].reverse().find((line) => /(?:Error|Exception|CUDA|out of memory)/i.test(line));
  if (specific) return safeReason(specific);
  return safeReason(lines[lines.length - 1] || 'Training runner failed');
}

function artifactFile(relativePath: string): string | null {
  const resolved = path.resolve(dataRoot, relativePath);
  const relative = path.relative(trainingRoot, resolved);
  return relative && !relative.startsWith('..') && !path.isAbsolute(relative) ? resolved : null;
}

async function fileHash(file: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    const stream = createReadStream(file);
    stream.on('error', reject);
    stream.on('data', (chunk: string | Buffer) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

async function scheduleResume(jobId: string, delayMs = 15_000): Promise<void> {
  if (retryTimers.has(jobId)) return;
  const timer = setTimeout(async () => {
    retryTimers.delete(jobId);
    const job = await prisma.trainingJob.findUnique({ where: { id: jobId } });
    if (job?.status === 'PAUSED_GPU') await launchJob(jobId);
  }, delayMs);
  retryTimers.set(jobId, timer);
}

async function reconcileRunnerReports(): Promise<void> {
  if (!existsSync(runnerReportsRoot)) return;
  for (const filename of readdirSync(runnerReportsRoot)) {
    if (!/^[0-9a-f-]{36}\.json$/i.test(filename)) continue;
    let report: RunnerEvent;
    try { report = JSON.parse(readFileSync(path.join(runnerReportsRoot, filename), 'utf8')) as RunnerEvent; }
    catch { continue; }
    const jobId = filename.slice(0, -'.json'.length);
    const job = await prisma.trainingJob.findUnique({ where: { id: jobId }, include: { modelVersion: true } });
    if (!job || job.modelVersion || !['RUNNING', 'EVALUATING', 'PAUSED_GPU'].includes(job.status)) continue;
    if (report.outcome === 'paused') {
      await prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'PAUSED_GPU', pauseReason: safeReason(report.reason), failureReason: null } });
      await scheduleResume(job.id, report.reason === 'LOW_SYSTEM_MEMORY' ? 60_000 : 15_000);
      continue;
    }
    if (report.outcome !== 'completed') continue;
    const artifactPath = String(report.artifactPath || '');
    const artifact = artifactFile(artifactPath);
    if (!artifact || !existsSync(artifact) || !/^[0-9a-f]{64}$/.test(String(report.artifactSha256 || '')) || await fileHash(artifact) !== report.artifactSha256) {
      await prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'FAILED', completedAt: new Date(), failureReason: 'Training artifact integrity check failed' } });
      continue;
    }
    const accepted = report.accepted === true;
    await prisma.$transaction([
      prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'SUCCEEDED', completedAt: new Date(), currentEpoch: job.totalEpochs } }),
      prisma.modelVersion.create({
        data: {
          trainingJobId: job.id,
          versionKey: `custom-${job.id.slice(0, 8)}`,
          baseModel: job.baseModel,
          artifactPath,
          artifactSha256: String(report.artifactSha256),
          status: accepted ? 'CANDIDATE' : 'REJECTED',
          evaluationMetrics: { ...(report.metrics as Record<string, unknown> || {}), labelMap: report.labelMap || {} },
          evaluatedAt: new Date(),
        },
      }),
    ]);
  }
}

async function launchJob(jobId: string): Promise<void> {
  const job = await prisma.trainingJob.findUnique({ where: { id: jobId }, include: { dataset: true } });
  if (!job || !['QUEUED', 'PAUSED_GPU'].includes(job.status)) return;
  const claimed = await prisma.trainingJob.updateMany({
    where: { id: job.id, status: { in: ['QUEUED', 'PAUSED_GPU'] } },
    data: { status: 'RUNNING', pauseReason: null, failureReason: null, startedAt: job.startedAt || new Date() },
  });
  if (claimed.count !== 1) return;

  const manifest = path.resolve(backendRoot, job.dataset.manifestPath);
  const model = path.join(workerRoot, 'models', job.baseModel);
  if (!existsSync(manifest) || !existsSync(model)) {
    await prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'FAILED', completedAt: new Date(), failureReason: 'Training source is unavailable' } });
    return;
  }

  const child = spawn(python, ['-m', 'training.runner', manifest, model, trainingRoot, job.id, String(job.totalEpochs)], {
    cwd: workerRoot,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let lineBuffer = '';
  let stderrBuffer = '';
  let runnerResult: RunnerEvent | null = null;
  let updateChain = Promise.resolve();
  const consumeLine = (line: string) => {
    if (!line.startsWith('SENTRIAI_EVENT ')) return;
    try {
      const event = JSON.parse(line.slice('SENTRIAI_EVENT '.length)) as RunnerEvent;
      if (event.event === 'progress' && typeof event.epoch === 'number') {
        updateChain = updateChain.then(() => prisma.trainingJob.update({ where: { id: job.id }, data: { currentEpoch: Math.min(job.totalEpochs, Math.max(0, event.epoch!)) } }).then(() => undefined));
      }
      if (event.event === 'evaluating') {
        updateChain = updateChain.then(() => prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'EVALUATING', currentEpoch: job.totalEpochs } }).then(() => undefined));
      }
      if (event.event === 'result') runnerResult = event;
    } catch { /* Ignore non-contract runner output. */ }
  };
  child.stdout.on('data', (chunk) => {
    lineBuffer += String(chunk);
    const lines = lineBuffer.split(/\r?\n/);
    lineBuffer = lines.pop() || '';
    lines.forEach(consumeLine);
  });
  child.stderr.on('data', (chunk) => { stderrBuffer = (stderrBuffer + String(chunk)).slice(-4_000); });
  child.on('error', () => { runnerResult = { event: 'result', reason: 'RUNNER_START_FAILED' }; });
  child.on('close', async (code) => {
    consumeLine(lineBuffer);
    await updateChain;
    try {
      if (runnerResult?.outcome === 'paused') {
        await prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'PAUSED_GPU', pauseReason: safeReason(runnerResult.reason), failureReason: null } });
        await scheduleResume(job.id, runnerResult.reason === 'LOW_SYSTEM_MEMORY' ? 60_000 : 15_000);
        return;
      }
      if (code !== 0 || !runnerResult || runnerResult.outcome !== 'completed') {
        await prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'FAILED', completedAt: new Date(), failureReason: runnerFailureReason(stderrBuffer || runnerResult?.reason || '') } });
        return;
      }
      const artifactPath = String(runnerResult.artifactPath || '');
      const artifact = artifactFile(artifactPath);
      if (!artifact || !existsSync(artifact) || !/^[0-9a-f]{64}$/.test(String(runnerResult.artifactSha256 || '')) || await fileHash(artifact) !== runnerResult.artifactSha256) {
        await prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'FAILED', completedAt: new Date(), failureReason: 'Training artifact integrity check failed' } });
        return;
      }
      const accepted = runnerResult.accepted === true;
      await prisma.$transaction([
        prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'SUCCEEDED', completedAt: new Date(), currentEpoch: job.totalEpochs } }),
        prisma.modelVersion.create({
          data: {
            trainingJobId: job.id,
            versionKey: `custom-${job.id.slice(0, 8)}`,
            baseModel: job.baseModel,
            artifactPath,
            artifactSha256: String(runnerResult.artifactSha256),
            status: accepted ? 'CANDIDATE' : 'REJECTED',
            evaluationMetrics: { ...(runnerResult.metrics as Record<string, unknown> || {}), labelMap: runnerResult.labelMap || {} },
            evaluatedAt: new Date(),
          },
        }),
      ]);
    } catch {
      await prisma.trainingJob.update({ where: { id: job.id }, data: { status: 'FAILED', completedAt: new Date(), failureReason: 'Cannot persist training result' } });
    }
  });
}

// A server restart must not discard a completed model that was written by the
// independent Python runner while the API was unavailable.
void reconcileRunnerReports().catch(() => undefined);

trainingJobsRouter.get('/', async (_req: Request, res: Response, next: NextFunction) => {
  try { return sendSuccess(res, await prisma.trainingJob.findMany({ orderBy: { requestedAt: 'desc' }, include: { dataset: true, modelVersion: true } })); } catch (error) { return next(error); }
});

trainingJobsRouter.post('/', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const datasetId = String(req.body?.datasetId || '');
    const dataset = await prisma.trainingDataset.findUnique({ where: { id: datasetId } });
    if (!dataset) throw new NotFoundError('Không tìm thấy dataset đã xuất');
    if (!existsSync(path.resolve(backendRoot, dataset.manifestPath))) throw new BadRequestError('Dataset snapshot không còn đầy đủ để train');
    const baseModel = String(req.body?.baseModel || 'yolo11n.pt');
    if (!allowedBaseModels.has(baseModel)) throw new BadRequestError('Base model không được hỗ trợ');
    const active = await prisma.trainingJob.count({ where: { status: { in: ['RUNNING', 'EVALUATING'] } } });
    if (active) throw new BadRequestError('Đã có một lần cải thiện nhận diện đang chạy');
    const job = await prisma.trainingJob.create({ data: { datasetId, baseModel, totalEpochs: 60, status: 'QUEUED' } });
    return sendCreated(res, job);
  } catch (error) { return next(error); }
});

trainingJobsRouter.post('/:id/start', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const job = await prisma.trainingJob.findUnique({ where: { id: req.params.id } });
    if (!job) throw new NotFoundError('Không tìm thấy lần cải thiện nhận diện');
    if (job.status !== 'QUEUED') throw new BadRequestError('Lần cải thiện này đã được bắt đầu');
    void launchJob(job.id);
    return sendSuccess(res, { id: job.id, status: 'RUNNING' });
  } catch (error) { return next(error); }
});

trainingJobsRouter.post('/:id/retry', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const job = await prisma.trainingJob.findUnique({ where: { id: req.params.id } });
    if (!job) throw new NotFoundError('KhĂ´ng tĂ¬m tháº¥y láº§n cáº£i thiá»‡n nháº­n diá»‡n');
    if (job.status !== 'FAILED') throw new BadRequestError('Chá»‰ cĂ³ thá»ƒ cháº¡y láº¡i má»™t láº§n cáº£i thiá»‡n bá»‹ lá»—i');
    const active = await prisma.trainingJob.count({ where: { status: { in: ['RUNNING', 'EVALUATING'] } } });
    if (active) throw new BadRequestError('ÄĂ£ cĂ³ má»™t láº§n cáº£i thiá»‡n nháº­n diá»‡n Ä‘ang cháº¡y');
    await prisma.trainingJob.update({
      where: { id: job.id },
      data: { status: 'QUEUED', pauseReason: null, failureReason: null, completedAt: null },
    });
    void launchJob(job.id);
    return sendSuccess(res, { id: job.id, status: 'RUNNING', resumedFromCheckpoint: true });
  } catch (error) { return next(error); }
});

trainingJobsRouter.get('/versions', async (_req: Request, res: Response, next: NextFunction) => {
  try { return sendSuccess(res, await prisma.modelVersion.findMany({ orderBy: { createdAt: 'desc' } })); } catch (error) { return next(error); }
});

trainingJobsRouter.post('/versions/:id/use', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const candidate = await prisma.modelVersion.findUnique({ where: { id: req.params.id } });
    if (!candidate) throw new NotFoundError('Không tìm thấy bản nhận diện mới');
    if (!['CANDIDATE', 'INACTIVE'].includes(candidate.status) || !candidate.evaluatedAt) throw new BadRequestError('Bản này chưa đạt điều kiện để sử dụng');
    const artifact = artifactFile(candidate.artifactPath);
    if (!artifact || !existsSync(artifact) || await fileHash(artifact) !== candidate.artifactSha256) throw new BadRequestError('File model không còn đúng phiên bản đã kiểm tra');
    await prisma.$transaction([
      prisma.modelVersion.updateMany({ where: { status: 'ACTIVE' }, data: { status: 'INACTIVE' } }),
      prisma.modelVersion.update({ where: { id: candidate.id }, data: { status: 'ACTIVE', activatedAt: new Date() } }),
    ]);
    return sendSuccess(res, { id: candidate.id, status: 'ACTIVE', message: 'Đã dùng bản nhận diện mới; base YOLO vẫn nhận người và xe nền' });
  } catch (error) { return next(error); }
});

trainingJobsRouter.post('/versions/return', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    await prisma.modelVersion.updateMany({ where: { status: 'ACTIVE' }, data: { status: 'INACTIVE' } });
    return sendSuccess(res, { status: 'BASE_ONLY', message: 'Đã quay về bản nhận diện nền' });
  } catch (error) { return next(error); }
});

export { trainingJobsRouter };
