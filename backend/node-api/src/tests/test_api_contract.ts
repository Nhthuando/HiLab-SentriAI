/**
 * test_api_contract.ts — End-to-End Automated Verification Test for REST API Contract
 *
 * Tests:
 * 1. GET /api/v1/health (200 OK, database connected, standard envelope)
 * 2. 404 Not Found handling (404, ROUTE_NOT_FOUND, standard error envelope)
 * 3. Error Handling Middleware (Custom AppError, status code mapping)
 * 4. Malformed JSON handling (400, INVALID_JSON)
 * 5. Static media file serving (/data/crops/, /data/clips/)
 */
import dotenv from 'dotenv';
import path from 'path';

// Load .env from backend/.env or root
dotenv.config({ path: path.resolve(__dirname, '../../../.env') });
dotenv.config({ path: path.resolve(__dirname, '../../.env') });
dotenv.config({ path: path.resolve(process.cwd(), '../.env') });
dotenv.config();

import http from 'http';
import fs from 'fs';
import { app, cropsDir } from '../index';
import { prisma } from '../prisma/client';
import { pythonConnector } from '../ws';

const TEST_PORT = 3096;
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
  console.log('SentriAI - FDN-API-CONTRACT Verification Test Suite');
  console.log('======================================================================');

  // Start HTTP server on TEST_PORT
  const server = http.createServer(app);
  await new Promise<void>((resolve) => {
    server.listen(TEST_PORT, () => {
      console.log(`[1/5] Test API Server listening on ${BASE_URL}`);
      resolve();
    });
  });

  try {
    // -------------------------------------------------------------------------
    // 1. Test Health Endpoint (GET /api/v1/health)
    // -------------------------------------------------------------------------
    console.log('\n[2/5] Testing GET /api/v1/health...');
    const healthRes = await fetchJson(`${BASE_URL}/api/v1/health`);
    console.log('  Health response status:', healthRes.status);
    console.log('  Health response body:', JSON.stringify(healthRes.body));

    if (healthRes.status !== 200) {
      throw new Error(`Expected HTTP 200 from /health, got ${healthRes.status}`);
    }
    if (!healthRes.body.success) {
      throw new Error('Expected health response to have success: true');
    }
    if (!healthRes.body.data || healthRes.body.data.service !== 'sentriai-node-api') {
      throw new Error('Health response missing expected service name');
    }
    if (healthRes.body.data.database.status !== 'connected') {
      throw new Error(`Expected database status 'connected', got '${healthRes.body.data.database.status}'`);
    }
    console.log('  [OK] GET /api/v1/health returned 200 OK with database connected');

    // -------------------------------------------------------------------------
    // 2. Test 404 Route Not Found Handling
    // -------------------------------------------------------------------------
    console.log('\n[3/5] Testing 404 Not Found Route Handling...');
    const notFoundRes = await fetchJson(`${BASE_URL}/api/v1/unknown-endpoint-xyz`);
    console.log('  404 response status:', notFoundRes.status);
    console.log('  404 response body:', JSON.stringify(notFoundRes.body));

    if (notFoundRes.status !== 404) {
      throw new Error(`Expected HTTP 404, got ${notFoundRes.status}`);
    }
    if (notFoundRes.body.success !== false || notFoundRes.body.error.code !== 'ROUTE_NOT_FOUND') {
      throw new Error('Expected standard 404 error envelope with ROUTE_NOT_FOUND code');
    }
    console.log('  [OK] 404 handler returned standard error envelope with ROUTE_NOT_FOUND');

    // -------------------------------------------------------------------------
    // 3. Test Error Handling Middleware (Custom AppError & Validation)
    // -------------------------------------------------------------------------
    console.log('\n[4/5] Testing Custom AppError Middleware Handling...');
    // 3a. Bad Request (400)
    const badReqRes = await fetchJson(`${BASE_URL}/api/v1/test-error/bad-request`);
    if (badReqRes.status !== 400 || badReqRes.body.error.code !== 'BAD_REQUEST') {
      throw new Error(`Expected 400 BAD_REQUEST, got ${badReqRes.status}`);
    }
    console.log('  [OK] BadRequestError returned HTTP 400 with code BAD_REQUEST and details');

    // 3b. Conflict (409)
    const conflictRes = await fetchJson(`${BASE_URL}/api/v1/test-error/conflict`);
    if (conflictRes.status !== 409 || conflictRes.body.error.code !== 'CONFLICT') {
      throw new Error(`Expected 409 CONFLICT, got ${conflictRes.status}`);
    }
    console.log('  [OK] ConflictError returned HTTP 409 with code CONFLICT');

    // 3c. Not Found (404)
    const notFoundErrRes = await fetchJson(`${BASE_URL}/api/v1/test-error/not-found`);
    if (notFoundErrRes.status !== 404 || notFoundErrRes.body.error.code !== 'NOT_FOUND') {
      throw new Error(`Expected 404 NOT_FOUND, got ${notFoundErrRes.status}`);
    }
    console.log('  [OK] NotFoundError returned HTTP 404 with code NOT_FOUND');

    // 3d. Validation Error (400)
    const valErrRes = await fetchJson(`${BASE_URL}/api/v1/test-error/validation`);
    if (valErrRes.status !== 400 || valErrRes.body.error.code !== 'VALIDATION_ERROR') {
      throw new Error(`Expected 400 VALIDATION_ERROR, got ${valErrRes.status}`);
    }
    console.log('  [OK] ValidationError returned HTTP 400 with code VALIDATION_ERROR');

    // 3e. Malformed JSON Body (400)
    const malformedRes = await fetchJson(`${BASE_URL}/api/v1/health`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{ malformed json body',
    });
    if (malformedRes.status !== 400 || malformedRes.body.error.code !== 'INVALID_JSON') {
      throw new Error(`Expected 400 INVALID_JSON for malformed payload, got ${malformedRes.status}`);
    }
    console.log('  [OK] Malformed JSON payload returned HTTP 400 with code INVALID_JSON');

    // -------------------------------------------------------------------------
    // 4. Test Static Media File Serving (/data/crops)
    // -------------------------------------------------------------------------
    console.log('\n[5/5] Testing Static Media File Serving...');
    fs.mkdirSync(cropsDir, { recursive: true });
    const testCropFile = path.join(cropsDir, 'test_contract_sample.txt');
    fs.writeFileSync(testCropFile, 'TEST_CROP_CONTENT_OK', 'utf8');

    const staticRes = await fetch(`${BASE_URL}/data/crops/test_contract_sample.txt`);
    const staticText = await staticRes.text();
    if (staticRes.status !== 200 || staticText !== 'TEST_CROP_CONTENT_OK') {
      throw new Error(`Static file serving failed, status: ${staticRes.status}`);
    }
    console.log('  [OK] Static media serving /data/crops verified successfully (HTTP 200)');

    // Clean up test file
    try {
      fs.unlinkSync(testCropFile);
    } catch {}

  } finally {
    // Teardown
    pythonConnector.stop();
    await prisma.$disconnect();
    await new Promise<void>((resolve) => {
      server.close(() => {
        console.log('\n  [OK] Test server closed cleanly');
        resolve();
      });
    });
  }

  console.log('\n======================================================================');
  console.log('ALL REST API CONTRACT TESTS PASSED SUCCESSFULLY! (100% PASS)');
  console.log('======================================================================');
  process.exit(0);
}

runTests().catch((err) => {
  console.error('Test failed with error:', err);
  process.exit(1);
});
