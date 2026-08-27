import assert from 'node:assert/strict';
import type { Content } from '@google/genai';
import type { PrismaClient } from '@prisma/client';
import {
  GeminiTimeoutError,
  QaGeminiService,
  type GeminiTransport,
} from '../ai/gemini';
import { executeQaTool, todayRange, type QaToolExecution } from '../ai/tools';

async function testTodayRange(): Promise<void> {
  const { start, end } = todayRange(new Date('2026-08-27T17:30:00.000Z'));
  assert.equal(start.toISOString(), '2026-08-27T17:00:00.000Z');
  assert.equal(end.toISOString(), '2026-08-28T17:00:00.000Z');
}

async function testToolUsesBoundedPrismaQuery(): Promise<void> {
  let countWhere: unknown;
  let findArgs: any;
  const client = {
    gateEvent: {
      count: async (args: unknown) => { countWhere = args; return 1; },
      findMany: async (args: unknown) => {
        findArgs = args;
        return [{
          id: '11111111-1111-4111-8111-111111111111', cameraId: 'GATE-01', lane: 'IN_1',
          licensePlate: '15A12345', status: 'STRANGER', confidence: 0.91, clipPath: null,
          videoTimecode: null, eventTimestamp: new Date('2026-08-27T03:00:00.000Z'),
        }];
      },
    },
  } as unknown as PrismaClient;
  const result = await executeQaTool('get_stranger_vehicles_today', {}, client);
  assert.equal(result.result.count, 1);
  assert.equal((result.result.events as unknown[]).length, 1);
  assert.equal(result.clips.length, 0);
  assert.ok(countWhere);
  assert.equal(findArgs.take, 50);
}

async function testFunctionCallingLoop(): Promise<void> {
  let calls = 0;
  const transport: GeminiTransport = {
    async generate(contents: Content[]) {
      calls += 1;
      if (calls === 1) {
        return {
          functionCalls: [{ id: 'call-1', name: 'get_stranger_vehicles_today', args: {} }],
          modelContent: {
            role: 'model',
            parts: [{ functionCall: { id: 'call-1', name: 'get_stranger_vehicles_today', args: {} } }],
          },
        };
      }
      assert.equal(contents.length, 3);
      return { text: 'Hôm nay có 1 xe lạ vào cổng.' };
    },
  };
  const toolExecution: QaToolExecution = {
    name: 'get_stranger_vehicles_today',
    result: { count: 1, events: [] },
    clips: [],
  };
  const service = new QaGeminiService(transport, async () => toolExecution, 100);
  const answer = await service.answer('Hôm nay có bao nhiêu xe lạ vào?');
  assert.equal(answer.text, 'Hôm nay có 1 xe lạ vào cổng.');
  assert.deepEqual(answer.sources, ['get_stranger_vehicles_today']);
  assert.equal(calls, 2);
}

async function testAreaActivitySummaryAndDeferredEvidence(): Promise<void> {
  const rows = [
    {
      id: '33333333-3333-4333-8333-333333333333', cameraId: 'BAI-KIEM', zoneId: null,
      zoneName: 'Khu nâng hạ', objectLabel: 'Xe nâng', canonicalClass: 'forklift',
      policyResult: 'ALLOWED', sessionStatus: 'CLOSED',
      enteredAt: new Date(Date.now() - 300_000), lastSeenAt: new Date(Date.now() - 180_000),
      exitedAt: new Date(Date.now() - 180_000), durationSeconds: 120, trackId: 7,
      entryPoint: { x: 0.4, y: 0.7 }, sourceKind: 'LOCAL_FILE', sourceRef: 'sample.mp4',
      sourcePositionSeconds: 84, sourceTimestamp: null, eventFingerprint: 'a'.repeat(64),
      violationId: null, clipPath: null, clipStatus: 'NOT_REQUESTED', clipRequestedAt: null,
      clipError: null, createdAt: new Date(), updatedAt: new Date(),
    },
    {
      id: '44444444-4444-4444-8444-444444444444', cameraId: 'BAI-KIEM', zoneId: null,
      zoneName: 'Khu nâng hạ', objectLabel: 'Xe nâng', canonicalClass: 'forklift',
      policyResult: 'VIOLATION', sessionStatus: 'CLOSED',
      enteredAt: new Date(Date.now() - 600_000), lastSeenAt: new Date(Date.now() - 360_000),
      exitedAt: new Date(Date.now() - 360_000), durationSeconds: 240, trackId: 8,
      entryPoint: { x: 0.6, y: 0.7 }, sourceKind: 'LOCAL_FILE', sourceRef: 'sample.mp4',
      sourcePositionSeconds: 180, sourceTimestamp: null, eventFingerprint: 'b'.repeat(64),
      violationId: null, clipPath: null, clipStatus: 'NOT_REQUESTED', clipRequestedAt: null,
      clipError: null, createdAt: new Date(), updatedAt: new Date(),
    },
  ];
  const client = {
    areaActivitySession: {
      findMany: async () => rows,
      findUnique: async ({ where }: any) => rows.find((row) => row.id === where.id) ?? null,
    },
    areaActivityCollectionState: {
      findUnique: async () => ({ cameraId: 'BAI-KIEM', startedAt: new Date(Date.now() - 3_600_000), lastObservedAt: new Date() }),
    },
  } as unknown as PrismaClient;
  const execution = await executeQaTool('get_area_activity_summary', { objectLabel: 'Xe nâng' }, client);
  assert.deepEqual((execution.result.summary as any), {
    entrySessions: 2,
    completedExits: 2,
    openSessions: 0,
    totalObservedSeconds: 360,
    averageSeconds: 180,
    maximumSeconds: 240,
    allowedSessions: 1,
    violationSessions: 1,
    byZone: { 'Khu nâng hạ': 2 },
    firstEntryLocal: (execution.result.summary as any).firstEntryLocal,
    latestEntryLocal: (execution.result.summary as any).latestEntryLocal,
  });
  assert.equal(execution.evidence?.eventId, rows[0].id);
  assert.equal(execution.evidence?.clipStatus, 'NOT_REQUESTED');
  assert.equal(execution.evidence?.canRequestClip, true);
}

async function testTimeoutMapping(): Promise<void> {
  const transport: GeminiTransport = {
    async generate(_contents, signal) {
      await new Promise<void>((_resolve, reject) => {
        signal.addEventListener('abort', () => {
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        }, { once: true });
      });
      return {};
    },
  };
  const service = new QaGeminiService(transport, executeQaTool, 5);
  await assert.rejects(() => service.answer('test timeout'), GeminiTimeoutError);
}

async function main(): Promise<void> {
  await testTodayRange();
  await testToolUsesBoundedPrismaQuery();
  await testFunctionCallingLoop();
  await testAreaActivitySummaryAndDeferredEvidence();
  await testTimeoutMapping();
  console.log('VS-QA-CHAT focused tests passed (timezone, Prisma tools, function loop, timeout).');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
