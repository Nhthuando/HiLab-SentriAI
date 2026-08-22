/**
 * Mark an orphaned runner job as recoverable without touching its checkpoint.
 * Use only after verifying that no Python trainer process remains for the job.
 */
import dotenv from 'dotenv';
import path from 'path';
import { prisma } from '../prisma/client';

dotenv.config({ path: path.resolve(__dirname, '../../../.env') });

async function main(): Promise<void> {
  const jobId = process.argv[2] || '';
  if (!/^[0-9a-f-]{36}$/i.test(jobId)) {
    throw new Error('Usage: ts-node src/scripts/recover-training-job.ts <training-job-uuid>');
  }
  const job = await prisma.trainingJob.findUnique({ where: { id: jobId } });
  if (!job) throw new Error('Training job was not found');
  if (!['RUNNING', 'EVALUATING'].includes(job.status)) {
    throw new Error(`Only RUNNING or EVALUATING jobs can be recovered; current status is ${job.status}`);
  }
  await prisma.trainingJob.update({
    where: { id: jobId },
    data: {
      status: 'FAILED',
      failureReason: 'Runner process stopped during API restart; checkpoint retained',
      completedAt: new Date(),
    },
  });
  console.log(JSON.stringify({ id: jobId, status: 'FAILED', checkpointPreserved: true }));
}

main()
  .catch((error) => { console.error(error instanceof Error ? error.message : 'Training recovery failed'); process.exitCode = 1; })
  .finally(async () => { await prisma.$disconnect(); });
