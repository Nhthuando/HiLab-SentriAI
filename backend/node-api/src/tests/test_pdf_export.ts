/**
 * test_pdf_export.ts — Automated test suite for PDF Generation (Violations & Shift Handover)
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
import { pdfService } from '../services/pdfService';
import { prisma } from '../prisma/client';

async function runPdfTests() {
  console.log('--- [Test 1/2] Generate Shift Handover Report PDF ---');
  const mockAiSummary =
    `**BIÊN BẢN BÀN GIAO CA TRỰC AN NINH (06:00 - 14:00)**\n\n` +
    `1. Hoạt động Cổng (GATE-01):\n` +
    `- Tổng lượt xe qua cổng: 24 lượt\n` +
    `- Xe quen: 20 lượt | Xe lạ: 4 lượt (51C-123.45, 60A-999.88)\n\n` +
    `2. An ninh Khu vực (BAI-KIEM):\n` +
    `- Tổng lượt đối tượng vào zone: 12 lượt\n` +
    `- Vi phạm zone cấm: 1 vụ (Xe nâng hoạt động sai khung giờ lúc 09:30)\n\n` +
    `3. Đánh giá bàn giao: Tình hình ổn định.`;

  const shiftPdfBuffer = await pdfService.generateShiftReportPdf({
    shiftName: 'BÁO CÁO BÀN GIAO CA SÁNG',
    timeWindow: '06:00 - 14:00 (03/09/2026)',
    summaryText: mockAiSummary,
  });

  assert.ok(Buffer.isBuffer(shiftPdfBuffer), 'Must return a Node.js Buffer');
  assert.ok(shiftPdfBuffer.length > 2000, `PDF size must be substantial (actual: ${shiftPdfBuffer.length} bytes)`);
  const headerStr = shiftPdfBuffer.subarray(0, 8).toString('ascii');
  assert.match(headerStr, /^%PDF-1\./, 'PDF header magic bytes must start with %PDF-1.');
  console.log(`✓ Shift handover PDF generated (${shiftPdfBuffer.length} bytes)`);

  console.log('--- [Test 2/2] Generate Incident Violation Report PDF ---');
  // Look up an existing violation or create a temporary one
  let testViolation = await prisma.zoneViolation.findFirst({
    include: { zone: true },
  });

  let createdTemp = false;
  if (!testViolation) {
    let testZone = await prisma.zone.findFirst();
    if (!testZone) {
      testZone = await prisma.zone.create({
        data: {
          cameraId: 'BAI-KIEM',
          name: 'Zone Test PDF',
          polygonPoints: [[10, 10], [90, 10], [90, 90], [10, 90]],
        },
      });
    }
    testViolation = await prisma.zoneViolation.create({
      data: {
        cameraId: 'BAI-KIEM',
        zoneId: testZone.id,
        objectLabel: 'forklift',
        status: 'CLOSED',
        durationSeconds: 120,
        enteredAt: new Date(Date.now() - 3600 * 1000),
        exitedAt: new Date(),
      },
      include: { zone: true },
    });
    createdTemp = true;
  }

  const violationPdfBuffer = await pdfService.generateViolationPdf(testViolation.id);
  assert.ok(Buffer.isBuffer(violationPdfBuffer), 'Must return a Buffer');
  assert.ok(violationPdfBuffer.length > 2000, `Violation PDF size must be > 2KB (actual: ${violationPdfBuffer.length} bytes)`);
  assert.match(violationPdfBuffer.subarray(0, 8).toString('ascii'), /^%PDF-1\./);
  console.log(`✓ Incident violation PDF generated (${violationPdfBuffer.length} bytes)`);

  if (createdTemp && testViolation) {
    await prisma.zoneViolation.delete({ where: { id: testViolation.id } }).catch(() => {});
  }

  console.log('\n========================================');
  console.log('All PDF Generation Tests Passed Successfully!');
  console.log('========================================');
}

runPdfTests()
  .catch((err) => {
    console.error('PDF test failed:', err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
