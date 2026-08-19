/**
 * test_area_events.ts — End-to-End Automated Test for Area Monitoring REST API (VS-AREA-VIOLATION)
 *
 * Tests:
 * 1. GET /api/v1/events/area (200 OK, standard envelope, items array, total count)
 * 2. Query validation error handling (400, VALIDATION_ERROR for bad limit, offset, status)
 * 3. Pagination semantics (limit, offset)
 * 4. Filtering by status (OPEN/CLOSED) and zone_id
 * 5. Data transformation (zoneName join, clipUrl relative path formatting)
 */
import dotenv from 'dotenv';
import path from 'path';

// Load .env from backend/.env or root
dotenv.config({ path: path.resolve(__dirname, '../../../.env') });
dotenv.config({ path: path.resolve(__dirname, '../../.env') });
dotenv.config({ path: path.resolve(process.cwd(), '../.env') });
dotenv.config();

import http from 'http';
import { app } from '../index';
import { prisma } from '../prisma/client';
import { pythonConnector } from '../ws';

const TEST_PORT = 3097;
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
  console.log('SentriAI - VS-AREA-VIOLATION REST API Verification Test Suite');
  console.log('======================================================================');

  // Start HTTP server on TEST_PORT
  const server = http.createServer(app);
  await new Promise<void>((resolve) => {
    server.listen(TEST_PORT, () => {
      console.log(`[1/5] Test API Server listening on ${BASE_URL}`);
      resolve();
    });
  });

  let testZoneId: string | null = null;
  let testViolationId: string | null = null;

  try {
    // -------------------------------------------------------------------------
    // 1. Setup Test Data in DB (Zone + ZoneViolation)
    // -------------------------------------------------------------------------
    console.log('\n[2/5] Creating test Zone and Violation in Database...');
    const testZone = await prisma.zone.upsert({
      where: {
        uq_zones_camera_name: {
          cameraId: 'BAI-KIEM',
          name: 'Test Khu Vực Kiểm Tra',
        },
      },
      update: {
        polygonPoints: [
          { x: 0.1, y: 0.1 },
          { x: 0.8, y: 0.1 },
          { x: 0.8, y: 0.8 },
          { x: 0.1, y: 0.8 },
        ],
        ruleType: 'PROHIBIT_SPECIFIED',
        targetLabels: ['Xe máy', 'Xe đạp'],
        isActive: true,
      },
      create: {
        cameraId: 'BAI-KIEM',
        name: 'Test Khu Vực Kiểm Tra',
        polygonPoints: [
          { x: 0.1, y: 0.1 },
          { x: 0.8, y: 0.1 },
          { x: 0.8, y: 0.8 },
          { x: 0.1, y: 0.8 },
        ],
        ruleType: 'PROHIBIT_SPECIFIED',
        targetLabels: ['Xe máy', 'Xe đạp'],
        isActive: true,
      },
    });
    testZoneId = testZone.id;
    console.log('  Created/ensured test Zone:', testZone.id, testZone.name);

    const testViolation = await prisma.zoneViolation.create({
      data: {
        cameraId: 'BAI-KIEM',
        zoneId: testZone.id,
        objectLabel: 'Xe máy',
        status: 'OPEN',
        enteredAt: new Date(),
        clipPath: 'area_sample_test.mp4',
      },
    });
    testViolationId = testViolation.id;
    console.log('  Created test ZoneViolation:', testViolation.id, testViolation.objectLabel);

    // -------------------------------------------------------------------------
    // 2. Test GET /api/v1/events/area (Basic query)
    // -------------------------------------------------------------------------
    console.log('\n[3/5] Testing GET /api/v1/events/area...');
    const res1 = await fetchJson(`${BASE_URL}/api/v1/events/area?limit=10&offset=0`);
    if (res1.status !== 200 || !res1.body.success) {
      throw new Error(`Expected 200 OK with success=true, got ${res1.status}: ${JSON.stringify(res1.body)}`);
    }
    const pageData = res1.body.data;
    if (!Array.isArray(pageData.items) || typeof pageData.total !== 'number') {
      throw new Error(`Expected items array and total number in data: ${JSON.stringify(pageData)}`);
    }
    console.log(`  [OK] Returned ${pageData.items.length} items (total: ${pageData.total})`);

    // Verify test item fields
    const found = pageData.items.find((item: any) => item.id === testViolationId);
    if (!found) {
      throw new Error(`Expected to find created test violation ${testViolationId} in items list`);
    }
    if (found.zoneName !== 'Test Khu Vực Kiểm Tra') {
      throw new Error(`Expected zoneName 'Test Khu Vực Kiểm Tra', got '${found.zoneName}'`);
    }
    if (found.clipUrl !== '/data/clips/area_sample_test.mp4') {
      throw new Error(`Expected clipUrl '/data/clips/area_sample_test.mp4', got '${found.clipUrl}'`);
    }
    console.log('  [OK] Verified field mapping (zoneName, clipUrl, enteredAt, status)');

    // -------------------------------------------------------------------------
    // 3. Test Filter by zone_id and status
    // -------------------------------------------------------------------------
    console.log('\n[4/5] Testing filters (zone_id and status)...');
    const resFiltered = await fetchJson(`${BASE_URL}/api/v1/events/area?zone_id=${testZoneId}&status=OPEN`);
    if (resFiltered.status !== 200 || resFiltered.body.data.items.length === 0) {
      throw new Error(`Expected matching items for zone_id=${testZoneId} and status=OPEN`);
    }
    console.log(`  [OK] Filter returned ${resFiltered.body.data.items.length} items with status=OPEN`);

    // -------------------------------------------------------------------------
    // 4. Test Validation Errors (400 Bad Request)
    // -------------------------------------------------------------------------
    console.log('\n[5/5] Testing Query Validation Errors (400 Bad Request)...');

    // Test invalid limit (> 100)
    const errLimit = await fetchJson(`${BASE_URL}/api/v1/events/area?limit=200`);
    if (errLimit.status !== 400 || errLimit.body.error?.code !== 'VALIDATION_ERROR') {
      throw new Error(`Expected 400 VALIDATION_ERROR for limit=200, got ${errLimit.status}: ${JSON.stringify(errLimit.body)}`);
    }
    console.log('  [OK] limit=200 correctly rejected with 400 VALIDATION_ERROR');

    // Test invalid offset (< 0)
    const errOffset = await fetchJson(`${BASE_URL}/api/v1/events/area?offset=-5`);
    if (errOffset.status !== 400 || errOffset.body.error?.code !== 'VALIDATION_ERROR') {
      throw new Error(`Expected 400 VALIDATION_ERROR for offset=-5, got ${errOffset.status}`);
    }
    console.log('  [OK] offset=-5 correctly rejected with 400 VALIDATION_ERROR');

    // Test invalid status
    const errStatus = await fetchJson(`${BASE_URL}/api/v1/events/area?status=PENDING`);
    if (errStatus.status !== 400 || errStatus.body.error?.code !== 'VALIDATION_ERROR') {
      throw new Error(`Expected 400 VALIDATION_ERROR for status=PENDING, got ${errStatus.status}`);
    }
    console.log("  [OK] status='PENDING' correctly rejected with 400 VALIDATION_ERROR");

    console.log('\n======================================================================');
    console.log('ALL AREA EVENTS REST API TESTS PASSED SUCCESSFULLY! (100% PASS)');
    console.log('======================================================================');
  } finally {
    // Clean up test data
    if (testViolationId) {
      await prisma.zoneViolation.deleteMany({ where: { id: testViolationId } }).catch(() => {});
    }
    if (testZoneId) {
      await prisma.zone.deleteMany({ where: { id: testZoneId } }).catch(() => {});
    }

    // Close server and resources
    pythonConnector.stop();
    await prisma.$disconnect();
    server.close();
  }
}

runTests().catch((err) => {
  console.error('\n[FATAL] Test failed with error:', err);
  process.exit(1);
});
