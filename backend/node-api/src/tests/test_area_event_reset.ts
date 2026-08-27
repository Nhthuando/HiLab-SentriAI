import assert from 'assert';

import {
  AreaEventResetUnavailableError,
  deleteAreaEventsViaWorker,
} from '../services/areaEventResetService';

async function run(): Promise<void> {
  process.env.PYTHON_WORKER_HTTP_URL = 'http://worker.test:8001/';
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const successFetch = (async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify({
      cameraId: 'BAI-KIEM',
      deletedRecords: 4,
      clearedActive: 1,
      clearedPending: 2,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as typeof fetch;

  const result = await deleteAreaEventsViaWorker(successFetch);
  assert.deepStrictEqual(result, {
    cameraId: 'BAI-KIEM',
    deletedRecords: 4,
    clearedActive: 1,
    clearedPending: 2,
  });
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].init?.method, 'DELETE');
  assert.strictEqual(
    calls[0].url,
    'http://worker.test:8001/cameras/BAI-KIEM/violations',
  );

  const unavailableFetch = (async () => new Response('offline', { status: 503 })) as typeof fetch;
  await assert.rejects(
    () => deleteAreaEventsViaWorker(unavailableFetch),
    AreaEventResetUnavailableError,
  );

  const failedFetch = (async () => {
    throw new Error('connection refused');
  }) as typeof fetch;
  await assert.rejects(
    () => deleteAreaEventsViaWorker(failedFetch),
    AreaEventResetUnavailableError,
  );

  const malformedFetch = (async () => new Response(JSON.stringify({
    cameraId: 'BAI-KIEM',
    deletedRecords: 'four',
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })) as typeof fetch;
  await assert.rejects(
    () => deleteAreaEventsViaWorker(malformedFetch),
    AreaEventResetUnavailableError,
  );

  console.log('Area event reset service tests passed.');
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
