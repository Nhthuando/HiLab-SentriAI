/**
 * test_shift_qa.ts — Automated test suite for Shift Handover QA Tool & Domain Skill Validation
 */
import dotenv from 'dotenv';
import path from 'path';

const envPaths = [
  path.resolve(__dirname, '../../.env'),
  path.resolve(__dirname, '../.env'),
  path.resolve(process.cwd(), '.env'),
  path.resolve(process.cwd(), '../.env'),
];
for (const envPath of envPaths) {
  dotenv.config({ path: envPath });
}

import assert from 'node:assert/strict';
import { shiftRange, executeQaTool } from '../ai/tools';
import { loadSentriAiDomainSkill, validateDomainSkill } from '../ai/domainSkill';
import { prisma } from '../prisma/client';

async function runShiftQaTests() {
  console.log('--- [Test 1/3] Domain Skill Verification ---');
  const skill = loadSentriAiDomainSkill();
  assert.ok(skill.includes('get_shift_report_data'), 'Skill must mention get_shift_report_data');
  assert.ok(skill.includes('ca sáng'), 'Skill must define ca sáng');
  assert.ok(skill.includes('ca chiều'), 'Skill must define ca chiều');
  assert.ok(validateDomainSkill(skill), 'Skill must pass strict validation');
  console.log('✓ Domain skill contains shift handover guidelines and passed validation');

  console.log('--- [Test 2/3] Shift Range Time Math ---');
  const rangeDay = shiftRange('06:00', '14:00', '2026-09-03');
  assert.equal(rangeDay.end.getTime() - rangeDay.start.getTime(), 8 * 3600 * 1000);
  assert.ok(rangeDay.label.includes('06:00 - 14:00'));

  const rangeNight = shiftRange('22:00', '06:00', '2026-09-03');
  assert.equal(rangeNight.end.getTime() - rangeNight.start.getTime(), 8 * 3600 * 1000);
  assert.ok(rangeNight.end > rangeNight.start, 'Night shift end time must be after start time (next day)');
  console.log('✓ Shift range calculation passed');

  console.log('--- [Test 3/3] get_shift_report_data Tool Execution ---');
  const execution = await executeQaTool(
    'get_shift_report_data',
    {
      startTime: '06:00',
      endTime: '14:00',
      date: '2026-09-03',
    },
    prisma,
  );

  assert.equal(execution.name, 'get_shift_report_data');
  const result = execution.result as any;
  assert.ok(result.timeWindow, 'Result must contain timeWindow');
  assert.ok(result.gate, 'Result must contain gate statistics');
  assert.equal(typeof result.gate.totalEntries, 'number');
  assert.equal(typeof result.gate.knownVehicles, 'number');
  assert.equal(typeof result.gate.strangerVehicles, 'number');
  assert.ok(Array.isArray(result.gate.sampleStrangerPlates));

  assert.ok(result.area, 'Result must contain area statistics');
  assert.equal(typeof result.area.totalSessions, 'number');
  assert.equal(typeof result.area.totalViolations, 'number');
  assert.ok(result.coverage, 'Result must contain coverage state');

  console.log('✓ Tool execution returned valid shift statistics schema:', {
    timeWindow: result.timeWindow,
    gate: result.gate,
    area: {
      totalSessions: result.area.totalSessions,
      totalViolations: result.area.totalViolations,
    },
  });

  console.log('\n========================================');
  console.log('All Shift Handover QA Tests Passed Successfully!');
  console.log('========================================');
}

runShiftQaTests()
  .catch((err) => {
    console.error('Shift QA test failed:', err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
