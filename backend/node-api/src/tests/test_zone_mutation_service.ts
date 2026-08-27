import assert from 'node:assert/strict';
import type { Prisma, Zone } from '@prisma/client';
import type { ZoneMutationRepository } from '../repositories/ZoneMutationRepository';
import { ZoneMutationService, ZoneNotFoundError } from '../services/zoneMutationService';

const zone: Zone = {
  id: 'zone-1',
  cameraId: 'BAI-KIEM',
  name: 'Zone 1',
  polygonPoints: [],
  ruleType: 'PROHIBIT_SPECIFIED',
  targetLabels: [],
  isActive: true,
  createdAt: new Date(0),
  updatedAt: new Date(0),
};

class FakeRepository implements ZoneMutationRepository {
  updateCalls = 0;
  deleteCalls = 0;
  updateError: unknown = null;
  deleteError: unknown = null;

  async update(_id: string, _data: Prisma.ZoneUpdateInput): Promise<Zone> {
    this.updateCalls += 1;
    if (this.updateError) throw this.updateError;
    return zone;
  }

  async delete(_id: string): Promise<void> {
    this.deleteCalls += 1;
    if (this.deleteError) throw this.deleteError;
  }
}

async function main(): Promise<void> {
  const repository = new FakeRepository();
  const service = new ZoneMutationService(repository);

  assert.equal(await service.update(zone.id, { name: 'Updated' }), zone);
  assert.equal(repository.updateCalls, 1);
  await service.delete(zone.id);
  assert.equal(repository.deleteCalls, 1);

  repository.updateError = Object.assign(new Error('missing'), { code: 'P2025' });
  await assert.rejects(
    () => service.update('missing', { name: 'Missing' }),
    ZoneNotFoundError,
  );

  repository.deleteError = Object.assign(new Error('already gone'), { code: 'P2025' });
  await service.delete('already-gone');
  assert.equal(repository.deleteCalls, 2);

  console.log('Zone mutation service tests passed.');
}

void main();
