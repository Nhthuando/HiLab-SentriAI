/** Import a local, user-provided YOLO archive into the immutable training store. */
import { spawn } from 'child_process';
import { existsSync } from 'fs';
import path from 'path';
import dotenv from 'dotenv';
import { prisma } from '../prisma/client';

const backendRoot = path.resolve(process.cwd(), '..');
dotenv.config({ path: path.join(backendRoot, '.env') });
const workerRoot = path.join(backendRoot, 'python-worker');
const datasetsRoot = path.join(backendRoot, 'data', 'training', 'datasets');
const externalRoot = path.join(backendRoot, 'data', 'external-datasets');
const python = path.join(workerRoot, '.venv', 'Scripts', 'python.exe');
const eventPrefix = 'SENTRIAI_EXTERNAL_DATASET ';

type ImportResult = {
  contentHash: string;
  manifestPath: string;
  sampleCount: number;
  sourceCount: number;
  splits: Record<string, number>;
  labels: string[];
};

function isInside(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return Boolean(relative) && !relative.startsWith('..') && !path.isAbsolute(relative);
}

function runImporter(archive: string): Promise<ImportResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(python, ['-m', 'training.external_yolo_importer', archive, datasetsRoot], {
      cwd: workerRoot,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    let errors = '';
    child.stdout.on('data', (chunk) => { output += String(chunk); });
    child.stderr.on('data', (chunk) => { errors += String(chunk); });
    child.on('error', () => reject(new Error('Cannot start external dataset importer')));
    child.on('close', (code) => {
      const event = output.split(/\r?\n/).find((line) => line.startsWith(eventPrefix));
      if (code !== 0 || !event) return reject(new Error(errors.trim() || 'External dataset import failed'));
      try { resolve(JSON.parse(event.slice(eventPrefix.length)) as ImportResult); }
      catch { reject(new Error('External dataset importer returned an invalid result')); }
    });
  });
}

async function main(): Promise<void> {
  const argument = process.argv[2];
  if (!argument) throw new Error('Usage: ts-node src/scripts/import-external-yolo.ts <archive.zip>');
  const archive = path.resolve(process.cwd(), argument);
  if (!isInside(externalRoot, archive) || !existsSync(archive)) {
    throw new Error('Archive must be an existing .zip inside backend/data/external-datasets');
  }
  const result = await runImporter(archive);
  const manifest = path.resolve(result.manifestPath);
  if (!isInside(datasetsRoot, manifest) || !existsSync(manifest) || !/^[0-9a-f]{64}$/.test(result.contentHash)) {
    throw new Error('External dataset importer returned an unsafe snapshot');
  }
  const existing = await prisma.trainingDataset.findUnique({ where: { contentHash: result.contentHash } });
  const dataset = existing || await prisma.trainingDataset.create({
    data: {
      manifestPath: path.relative(backendRoot, manifest).replace(/\\/g, '/'),
      contentHash: result.contentHash,
      sampleCount: result.sampleCount,
      sourceCount: result.sourceCount,
    },
  });
  console.log(JSON.stringify({ imported: !existing, reused: Boolean(existing), dataset, splits: result.splits, labels: result.labels }, null, 2));
}

main()
  .catch((error) => { console.error(error instanceof Error ? error.message : 'External dataset import failed'); process.exitCode = 1; })
  .finally(async () => { await prisma.$disconnect(); });
