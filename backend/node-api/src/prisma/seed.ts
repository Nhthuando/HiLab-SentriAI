/**
 * prisma/seed.ts — Initial Database Seed for SentriAI
 *
 * Seeds standard object labels and camera zones into PostgreSQL Neon DB.
 */
import dotenv from 'dotenv';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../../../../.env') });
dotenv.config({ path: path.resolve(__dirname, '../../../.env') });
dotenv.config({ path: path.resolve(__dirname, '../../.env') });
dotenv.config();

import { prisma } from './client';

async function seed() {
  console.log('Seeding initial object labels and zones into Neon Database...');

  // 1. Seed Object Labels
  const labels = [
    { baseClass: 'truck', vietnameseName: 'Container' },
    { baseClass: 'truck', vietnameseName: 'Xe tải' },
    { baseClass: 'truck', vietnameseName: 'Xe nâng' },
    { baseClass: 'truck', vietnameseName: 'Xe cẩu' },
    { baseClass: 'car', vietnameseName: 'Xe con' },
    { baseClass: 'motorcycle', vietnameseName: 'Xe máy' },
    { baseClass: 'bicycle', vietnameseName: 'Xe đạp' },
    { baseClass: 'person', vietnameseName: 'Người' },
  ];

  for (const lbl of labels) {
    await prisma.objectLabel.upsert({
      where: { vietnameseName: lbl.vietnameseName },
      update: lbl,
      create: lbl,
    });
  }
  console.log(`[Seed] Seeded ${labels.length} object labels.`);

  // 2. Seed Camera Zones
  const zones = [
    // BAI-KIEM Zones
    {
      cameraId: 'BAI-KIEM',
      name: 'Zone cấm PT cá nhân',
      polygonPoints: [
        { x: 0.06, y: 0.30 },
        { x: 0.34, y: 0.28 },
        { x: 0.36, y: 0.60 },
        { x: 0.04, y: 0.66 },
      ],
      ruleType: 'PROHIBIT_SPECIFIED',
      targetLabels: ['Xe máy', 'Xe đạp', 'Xe con', 'Người'],
      isActive: true,
    },
    {
      cameraId: 'BAI-KIEM',
      name: 'Zone làn di chuyển',
      polygonPoints: [
        { x: 0.38, y: 0.42 },
        { x: 0.52, y: 0.42 },
        { x: 0.46, y: 0.94 },
        { x: 0.08, y: 0.94 },
      ],
      ruleType: 'ALLOW_SPECIFIED',
      targetLabels: ['Container', 'Xe nâng', 'Xe tải'],
      isActive: true,
    },
    {
      cameraId: 'BAI-KIEM',
      name: 'Zone bãi kiểm',
      polygonPoints: [
        { x: 0.54, y: 0.52 },
        { x: 0.88, y: 0.58 },
        { x: 0.92, y: 0.90 },
        { x: 0.48, y: 0.92 },
      ],
      ruleType: 'ALLOW_SPECIFIED',
      targetLabels: ['Container', 'Xe nâng', 'Xe tải'],
      isActive: true,
    },
    // GATE-01 Zones
    {
      cameraId: 'GATE-01',
      name: 'Làn IN 1',
      polygonPoints: [
        { x: 0.36, y: 0.54 },
        { x: 0.50, y: 0.54 },
        { x: 0.42, y: 0.95 },
        { x: 0.10, y: 0.95 },
      ],
      ruleType: 'ALLOW_SPECIFIED',
      targetLabels: ['Container', 'Xe tải'],
      isActive: true,
    },
    {
      cameraId: 'GATE-01',
      name: 'Làn IN 2',
      polygonPoints: [
        { x: 0.52, y: 0.54 },
        { x: 0.66, y: 0.54 },
        { x: 0.95, y: 0.95 },
        { x: 0.47, y: 0.95 },
      ],
      ruleType: 'ALLOW_SPECIFIED',
      targetLabels: ['Container', 'Xe tải'],
      isActive: true,
    },
  ];

  for (const z of zones) {
    await prisma.zone.upsert({
      where: {
        uq_zones_camera_name: {
          cameraId: z.cameraId,
          name: z.name,
        },
      },
      update: z,
      create: z,
    });
  }
  console.log(`[Seed] Seeded ${zones.length} zones.`);
  console.log('Database seed completed successfully!');
}

seed()
  .catch((err) => {
    console.error('Seed error:', err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
