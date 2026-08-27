import assert from 'node:assert/strict';
import {
  AreaEventClipUnavailableError,
  decodeAreaClipState,
  requestAreaEventClip,
} from '../services/areaEventClipService';

async function main(): Promise<void> {
  const violationId = '11111111-1111-4111-8111-111111111111';

  const decoded = decodeAreaClipState({
    violationId,
    status: 'READY',
    clipUrl: `/data/clips/area_${violationId}.mp4`,
    sourceRef: 'D:\\secret\\video.mp4',
  });
  assert.deepEqual(decoded, {
    violationId,
    status: 'READY',
    clipUrl: `/data/clips/area_${violationId}.mp4`,
  });
  assert.equal('sourceRef' in decoded, false);

  let requests = 0;
  const fakeFetch: typeof fetch = async (input, init) => {
    requests += 1;
    assert.match(String(input), new RegExp(`/cameras/BAI-KIEM/violations/${violationId}/clip$`));
    assert.equal(init?.method, 'POST');
    return new Response(JSON.stringify({
      violationId,
      status: 'QUEUED',
      clipUrl: null,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  const queued = await requestAreaEventClip(violationId, fakeFetch);
  assert.equal(queued.status, 'QUEUED');
  assert.equal(requests, 1);

  assert.throws(
    () => decodeAreaClipState({ violationId, status: 'UNKNOWN', clipUrl: null }),
    AreaEventClipUnavailableError,
  );

  console.log('[OK] Area event clip bridge validates and sanitizes worker responses.');
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
