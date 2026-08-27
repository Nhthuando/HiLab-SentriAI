import assert from 'node:assert/strict';
import type { PrismaClient } from '@prisma/client';
import { requestAreaActivityClip } from '../services/areaActivityClipService';

const ACTIVITY_ID = '11111111-1111-4111-8111-111111111111';
const VIOLATION_ID = '22222222-2222-4222-8222-222222222222';

function client(violationId: string | null): PrismaClient {
  return {
    areaActivitySession: {
      findFirst: async () => ({ violationId }),
    },
  } as unknown as PrismaClient;
}

async function testAllowedActivityCallsActivityWorker(): Promise<void> {
  let requestedUrl = '';
  const fakeFetch = async (input: string | URL | Request) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({ activityId: ACTIVITY_ID, status: 'QUEUED', clipUrl: null }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  const state = await requestAreaActivityClip(ACTIVITY_ID, client(null), fakeFetch as typeof fetch);
  assert.match(requestedUrl, new RegExp(`/activities/${ACTIVITY_ID}/clip$`));
  assert.deepEqual(state, { activityId: ACTIVITY_ID, status: 'QUEUED', clipId: null, clipUrl: null });
}

async function testViolationActivityDelegatesWithoutActivityFile(): Promise<void> {
  let requestedUrl = '';
  const fakeFetch = async (input: string | URL | Request) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({ violationId: VIOLATION_ID, status: 'READY', clipUrl: '/data/clips/a.mp4' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  const state = await requestAreaActivityClip(ACTIVITY_ID, client(VIOLATION_ID), fakeFetch as typeof fetch);
  assert.match(requestedUrl, new RegExp(`/violations/${VIOLATION_ID}/clip$`));
  assert.equal(state.clipId, VIOLATION_ID);
  assert.equal(state.clipUrl, `/api/v1/clips/${VIOLATION_ID}/stream`);
}

async function main(): Promise<void> {
  await testAllowedActivityCallsActivityWorker();
  await testViolationActivityDelegatesWithoutActivityFile();
  console.log('Area activity clip tests passed');
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
