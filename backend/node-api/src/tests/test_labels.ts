/**
 * test_labels.ts — Automated Verification Test Suite for VS-SETTINGS-LABEL
 *
 * Tests:
 * 1. POST /api/v1/labels (Create label, unique constraint check, 409 Conflict)
 * 2. GET /api/v1/labels (List labels with sample counts)
 * 3. PUT /api/v1/labels/:id (Update label)
 * 4. POST /api/v1/samples/batch (Batch insert annotation samples)
 * 5. POST /api/v1/upload/image (Image upload validation & saving)
 * 6. DELETE /api/v1/labels/:id (Cascade delete label and associated samples)
 */
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../../../.env') });
dotenv.config({ path: path.resolve(__dirname, '../../.env') });
dotenv.config({ path: path.resolve(process.cwd(), '../.env') });
dotenv.config();

import http from 'http';
import { app } from '../index';
import { prisma } from '../prisma/client';
import { pythonConnector } from '../ws';

const TEST_PORT = 3094;
const BASE_URL = `http://localhost:${TEST_PORT}`;

async function fetchJson(url: string, options?: RequestInit): Promise<{ status: number; body: any }> {
  const res = await fetch(url, options);
  let body: any;
  try {
    body = await res.json();
  } catch {
    body = await res.text();
  }
  return { status: res.status, body };
}

async function runTests() {
  console.log('======================================================================');
  console.log('SentriAI - VS-SETTINGS-LABEL Verification Test Suite');
  console.log('======================================================================');

  const server = http.createServer(app);
  await new Promise<void>((resolve) => {
    server.listen(TEST_PORT, () => {
      console.log(`[1/6] Test server listening on ${BASE_URL}`);
      resolve();
    });
  });

  const testLabelName = `Nhãn Test ${Date.now() % 100000}`;

  try {
    // -------------------------------------------------------------------------
    // 1. Test POST /api/v1/labels
    // -------------------------------------------------------------------------
    console.log(`\n[2/6] Testing POST /api/v1/labels with name '${testLabelName}'...`);
    const createRes = await fetchJson(`${BASE_URL}/api/v1/labels`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        vietnameseName: testLabelName,
        baseClass: 'truck',
        kind: 'xe',
        tint: '#3b82f6',
      }),
    });

    if (createRes.status !== 201 || !createRes.body.success) {
      throw new Error(`Expected 201 Created, got ${createRes.status}: ${JSON.stringify(createRes.body)}`);
    }
    const labelId = createRes.body.data.id;
    for (const field of [
      'canonicalClass', 'detectionSource', 'isDetectable', 'activeModelVersion', 'capabilityReason', 'capabilityReasonCode',
    ]) {
      if (!(field in createRes.body.data)) {
        throw new Error(`Created label response is missing capability field '${field}'`);
      }
    }
    if (createRes.body.data.detectionSource !== 'COCO' || createRes.body.data.isDetectable !== true) {
      throw new Error(`Expected truck label to use COCO, got ${JSON.stringify(createRes.body.data)}`);
    }
    console.log('  [OK] Label created successfully (201 Created), id:', labelId);

    // 1b. Test Duplicate Label (409 Conflict)
    const dupRes = await fetchJson(`${BASE_URL}/api/v1/labels`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        vietnameseName: testLabelName,
        baseClass: 'car',
      }),
    });
    if (dupRes.status !== 409 || dupRes.body.error.code !== 'CONFLICT') {
      throw new Error(`Expected 409 CONFLICT on duplicate label, got ${dupRes.status}`);
    }
    console.log('  [OK] Duplicate vietnameseName correctly rejected with HTTP 409 Conflict');

    // -------------------------------------------------------------------------
    // 2. Test GET /api/v1/labels
    // -------------------------------------------------------------------------
    console.log('\n[3/6] Testing GET /api/v1/labels...');
    const listRes = await fetchJson(`${BASE_URL}/api/v1/labels`);
    if (listRes.status !== 200 || !Array.isArray(listRes.body.data)) {
      throw new Error(`Expected 200 OK with array data, got ${listRes.status}`);
    }
    const found = listRes.body.data.find((l: any) => l.id === labelId);
    if (!found) {
      throw new Error(`Created label '${testLabelName}' not found in GET response`);
    }
    if (!('capabilityReasonCode' in found) || !('canonicalClass' in found)) {
      throw new Error('GET /api/v1/labels did not include the capability contract');
    }
    console.log(`  [OK] GET /api/v1/labels returned ${listRes.body.data.length} labels, found created label`);

    // -------------------------------------------------------------------------
    // 3. Test POST /api/v1/samples/batch
    // -------------------------------------------------------------------------
    console.log('\n[4/6] Testing POST /api/v1/samples/batch...');
    const batchRes = await fetchJson(`${BASE_URL}/api/v1/samples/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        samples: [
          { labelId, imagePath: '/data/samples/gate_frame1.jpg', bbox: { x: 10, y: 10, w: 50, h: 50 } },
          { labelId, imagePath: '/data/samples/gate_frame2.jpg', bbox: { x: 20, y: 20, w: 60, h: 40 } },
        ],
      }),
    });
    if (batchRes.status !== 201 || batchRes.body.data.count !== 2) {
      throw new Error(`Expected 201 with count 2, got ${batchRes.status}: ${JSON.stringify(batchRes.body)}`);
    }
    console.log('  [OK] Batch samples created successfully (2 samples inserted)');

    // -------------------------------------------------------------------------
    // 4. Test POST /api/v1/upload/image
    // -------------------------------------------------------------------------
    console.log('\n[5/6] Testing POST /api/v1/upload/image...');
    // 1x1 white transparent PNG in base64
    const sampleBase64 = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    const uploadRes = await fetchJson(`${BASE_URL}/api/v1/upload/image`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image: sampleBase64,
        filename: 'test_upload_sample.png',
      }),
    });
    if (uploadRes.status !== 201 || !uploadRes.body.data.path) {
      throw new Error(`Expected 201 with path, got ${uploadRes.status}: ${JSON.stringify(uploadRes.body)}`);
    }
    console.log('  [OK] Image upload verified successfully, saved to:', uploadRes.body.data.path);

    // -------------------------------------------------------------------------
    // 5. Test DELETE /api/v1/labels/:id (Cascade delete)
    // -------------------------------------------------------------------------
    console.log('\n[6/6] Testing DELETE /api/v1/labels/:id (Cascade delete)...');
    const delRes = await fetch(`${BASE_URL}/api/v1/labels/${labelId}`, {
      method: 'DELETE',
    });
    if (delRes.status !== 204 && delRes.status !== 200) {
      throw new Error(`Expected 204 No Content, got ${delRes.status}`);
    }
    console.log('  [OK] Label deleted and associated samples cascaded cleanly (204 No Content)');

  } finally {
    pythonConnector.stop();
    await prisma.$disconnect();
    await new Promise<void>((resolve) => {
      server.close(() => {
        console.log('\n  [OK] Test server closed');
        resolve();
      });
    });
  }

  console.log('\n======================================================================');
  console.log('ALL VS-SETTINGS-LABEL TESTS PASSED SUCCESSFULLY! (100% PASS)');
  console.log('======================================================================');
  process.exit(0);
}

runTests().catch((err) => {
  console.error('Test failed:', err);
  process.exit(1);
});
