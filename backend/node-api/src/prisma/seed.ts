import { prisma } from './client';

async function seed() {
  console.log('Seeding initial data to local database...');

  // Default vehicles
  const vehicles = [
    { plateNumber: '15R-158.45', status: 'KNOWN', note: 'Xe container Hải Phòng' },
    { plateNumber: '29A-123.45', status: 'KNOWN', note: 'Xe văn phòng Hà Nội' },
    { plateNumber: '51C-888.99', status: 'STRANGER', note: 'Xe lạ chưa khai báo' },
    { plateNumber: '7XYZ123', status: 'KNOWN', note: 'Xe chuyên gia quốc tế' },
    { plateNumber: 'ABC-1234', status: 'KNOWN', note: 'Xe đối tác vận tải' },
  ];

  for (const v of vehicles) {
    await prisma.registeredVehicle.upsert({
      where: { plateNumber: v.plateNumber },
      update: {},
      create: v,
    });
  }

  // Default object labels
  const labels = [
    { vietnameseName: 'Xe container', baseClass: 'truck' },
    { vietnameseName: 'Xe tải', baseClass: 'truck' },
    { vietnameseName: 'Xe ô tô con', baseClass: 'car' },
    { vietnameseName: 'Công nhân', baseClass: 'person' },
    { vietnameseName: 'Xe nâng', baseClass: 'forklift' },
  ];

  for (const l of labels) {
    await prisma.objectLabel.upsert({
      where: { vietnameseName: l.vietnameseName },
      update: {},
      create: l,
    });
  }

  console.log('✓ Seeding complete.');
  await prisma.$disconnect();
}

seed().catch((err) => {
  console.error('Seed error:', err);
  process.exit(1);
});
