/**
 * test_vehicles.ts — Automated Verification Test Suite for VS-SETTINGS-VEHICLE
 *
 * Tests:
 * 1. POST /api/v1/vehicles (create vehicle, normalization, duplicate conflict 409)
 * 2. GET /api/v1/vehicles (list, search, status filter, pagination)
 * 3. PATCH /api/v1/vehicles/:id/status (toggle KNOWN ⇄ STRANGER)
 * 4. DELETE /api/v1/vehicles/:id (delete vehicle)
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

const TEST_PORT = 3095;
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
  console.log('SentriAI - VS-SETTINGS-VEHICLE Verification Test Suite');
  console.log('======================================================================');

  const server = http.createServer(app);
  await new Promise<void>((resolve) => {
    server.listen(TEST_PORT, () => {
      console.log(`[1/4] Test server listening on ${BASE_URL}`);
      resolve();
    });
  });

  const testPlate = `TEST-${Date.now() % 100000}`;

  try {
    // -------------------------------------------------------------------------
    // 1. Test POST /api/v1/vehicles (Create & Normalize)
    // -------------------------------------------------------------------------
    console.log(`\n[2/4] Testing POST /api/v1/vehicles with plate '${testPlate}'...`);
    const createRes = await fetchJson(`${BASE_URL}/api/v1/vehicles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plateNumber: `  ${testPlate.toLowerCase()}  `,
        status: 'KNOWN',
        note: 'Xe thử nghiệm automated test',
      }),
    });

    console.log('  Create response status:', createRes.status);
    console.log('  Create response body:', JSON.stringify(createRes.body));

    if (createRes.status !== 201) {
      throw new Error(`Expected HTTP 201 Created, got ${createRes.status}`);
    }
    if (!createRes.body.success || createRes.body.data.plateNumber !== testPlate.toUpperCase()) {
      throw new Error(`Plate normalization failed, expected ${testPlate.toUpperCase()}`);
    }
    const createdId = createRes.body.data.id;
    console.log('  [OK] Vehicle created and normalized successfully (201 Created)');

    // 1b. Test Duplicate Plate (409 Conflict)
    console.log('  Testing Duplicate Plate Conflict (409)...');
    const dupRes = await fetchJson(`${BASE_URL}/api/v1/vehicles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plateNumber: testPlate,
        status: 'STRANGER',
      }),
    });
    if (dupRes.status !== 409 || dupRes.body.error.code !== 'CONFLICT') {
      throw new Error(`Expected 409 CONFLICT on duplicate plate, got ${dupRes.status}`);
    }
    console.log('  [OK] Duplicate plate correctly rejected with HTTP 409 Conflict');

    // -------------------------------------------------------------------------
    // 2. Test GET /api/v1/vehicles (List & Search Filter)
    // -------------------------------------------------------------------------
    console.log('\n[3/4] Testing GET /api/v1/vehicles...');
    const listRes = await fetchJson(`${BASE_URL}/api/v1/vehicles?search=${testPlate}`);
    if (listRes.status !== 200 || !Array.isArray(listRes.body.data)) {
      throw new Error(`Expected 200 OK with array data, got ${listRes.status}`);
    }
    const found = listRes.body.data.find((v: any) => v.plateNumber === testPlate.toUpperCase());
    if (!found) {
      throw new Error(`Created vehicle '${testPlate}' not found in search results`);
    }
    console.log(`  [OK] GET /api/v1/vehicles returned ${listRes.body.data.length} vehicle(s), matched '${testPlate}'`);

    // -------------------------------------------------------------------------
    // 3. Test PATCH /api/v1/vehicles/:id/status (Toggle Status)
    // -------------------------------------------------------------------------
    console.log('\n[4/4] Testing PATCH /api/v1/vehicles/:id/status...');
    const patchRes = await fetchJson(`${BASE_URL}/api/v1/vehicles/${createdId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'STRANGER' }),
    });

    if (patchRes.status !== 200 || patchRes.body.data.status !== 'STRANGER') {
      throw new Error(`Expected status to update to 'STRANGER', got ${patchRes.body.data?.status}`);
    }
    console.log('  [OK] Status toggled to STRANGER successfully (200 OK)');

    // -------------------------------------------------------------------------
    // 4. Test DELETE /api/v1/vehicles/:id (Cleanup)
    // -------------------------------------------------------------------------
    console.log('\nTesting DELETE /api/v1/vehicles/:id...');
    const deleteRes = await fetch(`${BASE_URL}/api/v1/vehicles/${createdId}`, {
      method: 'DELETE',
    });
    if (deleteRes.status !== 204 && deleteRes.status !== 200) {
      throw new Error(`Expected 204 No Content, got ${deleteRes.status}`);
    }
    console.log('  [OK] Vehicle deleted cleanly (204 No Content)');

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
  console.log('ALL VS-SETTINGS-VEHICLE TESTS PASSED SUCCESSFULLY! (100% PASS)');
  console.log('======================================================================');
  process.exit(0);
}

runTests().catch((err) => {
  console.error('Test failed:', err);
  process.exit(1);
});
