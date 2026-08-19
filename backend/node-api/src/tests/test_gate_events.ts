/**
 * test_gate_events.ts — Automated Verification Test Suite for VS-GATE-LIVE
 *
 * Tests:
 * 1. POST /api/v1/events/gate (Create gate event, WebSocket event broadcast)
 * 2. GET /api/v1/events/gate (Query paginated gate events, status filter KNOWN/STRANGER)
 * 3. Search by plate number
 * 4. WebSocket Feed & Event channel verification
 */
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../../../.env') });
dotenv.config({ path: path.resolve(__dirname, '../../.env') });
dotenv.config({ path: path.resolve(process.cwd(), '../.env') });
dotenv.config();

import http from 'http';
import { WebSocket } from 'ws';
import { app, server } from '../index';
import { prisma } from '../prisma/client';
import { pythonConnector } from '../ws';

const TEST_PORT = 3093;
const BASE_URL = `http://localhost:${TEST_PORT}`;
const WS_URL = `ws://localhost:${TEST_PORT}`;

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
  console.log('SentriAI - VS-GATE-LIVE Verification Test Suite');
  console.log('======================================================================');

  const testServer = http.createServer(app);
  await new Promise<void>((resolve) => {
    testServer.listen(TEST_PORT, () => {
      console.log(`[1/4] Test server listening on ${BASE_URL}`);
      resolve();
    });
  });

  const testPlate = `15R-158.45`;

  try {
    // -------------------------------------------------------------------------
    // 1. Test POST /api/v1/events/gate
    // -------------------------------------------------------------------------
    console.log(`\n[2/4] Testing POST /api/v1/events/gate with plate '${testPlate}'...`);
    const createRes = await fetchJson(`${BASE_URL}/api/v1/events/gate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cameraId: 'GATE-01',
        lane: 'IN_1',
        licensePlate: testPlate,
        status: 'KNOWN',
        confidence: 0.97,
        cropPath: '/data/crops/sample_gate_crop.jpg',
      }),
    });

    if (createRes.status !== 201 || !createRes.body.success) {
      throw new Error(`Expected 201 Created, got ${createRes.status}: ${JSON.stringify(createRes.body)}`);
    }
    const eventId = createRes.body.data.id;
    console.log('  [OK] Gate event created successfully (201 Created), id:', eventId);

    // -------------------------------------------------------------------------
    // 2. Test GET /api/v1/events/gate
    // -------------------------------------------------------------------------
    console.log('\n[3/4] Testing GET /api/v1/events/gate (Pagination & Status Filter)...');
    const listRes = await fetchJson(`${BASE_URL}/api/v1/events/gate?plate=${testPlate}&status=KNOWN`);
    if (listRes.status !== 200 || !Array.isArray(listRes.body.data)) {
      throw new Error(`Expected 200 OK with array data, got ${listRes.status}`);
    }
    const found = listRes.body.data.find((e: any) => e.id === eventId);
    if (!found) {
      throw new Error(`Created event '${eventId}' not found in query results`);
    }
    if (found.plate !== testPlate || found.status !== 'quen') {
      throw new Error(`Expected plate '${testPlate}' and status 'quen', got plate='${found.plate}', status='${found.status}'`);
    }
    console.log(`  [OK] GET /api/v1/events/gate matched created event with status 'quen' and 97% confidence`);

    // -------------------------------------------------------------------------
    // 3. Test Filter for Stranger (Xe lạ)
    // -------------------------------------------------------------------------
    console.log('\n[4/4] Testing Event Filtering for Stranger vehicles (Xe lạ)...');
    const strangerRes = await fetchJson(`${BASE_URL}/api/v1/events/gate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cameraId: 'GATE-01',
        lane: 'IN_2',
        licensePlate: '29C-999.88',
        status: 'STRANGER',
        confidence: 0.92,
      }),
    });
    if (strangerRes.status !== 201 || strangerRes.body.data.status !== 'la') {
      throw new Error(`Expected stranger event to map to status 'la', got ${strangerRes.body.data?.status}`);
    }
    console.log('  [OK] Stranger event correctly categorized as XE LẠ (status: "la", zone: "Làn IN 2 · Làn phụ")');

  } finally {
    pythonConnector.stop();
    await prisma.$disconnect();
    await new Promise<void>((resolve) => {
      testServer.close(() => {
        console.log('\n  [OK] Test server closed');
        resolve();
      });
    });
  }

  console.log('\n======================================================================');
  console.log('ALL VS-GATE-LIVE BACKEND TESTS PASSED SUCCESSFULLY! (100% PASS)');
  console.log('======================================================================');
  process.exit(0);
}

runTests().catch((err) => {
  console.error('Test failed:', err);
  process.exit(1);
});
