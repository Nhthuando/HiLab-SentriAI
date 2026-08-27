import assert from 'node:assert/strict';
import type { ModelVersion } from '@prisma/client';
import type {
  DetectionControlRepository,
  ObjectLabelWithSampleCount,
} from '../repositories/DetectionControlRepository';
import { DetectionCapabilityService } from '../services/detectionCapabilityService';

class FakeRepository implements DetectionControlRepository {
  activeCalls = 0;
  labelCalls = 0;

  async findActiveModel(): Promise<ModelVersion | null> {
    this.activeCalls += 1;
    return null;
  }

  async listLabelsWithSampleCount(): Promise<ObjectLabelWithSampleCount[]> {
    this.labelCalls += 1;
    return [{
      id: 'label-1',
      vietnameseName: 'Xe tải',
      baseClass: 'truck',
      createdAt: new Date(0),
      updatedAt: new Date(0),
      _count: { samples: 0 },
    }];
  }
}

async function main(): Promise<void> {
  let now = 1_000;
  const repository = new FakeRepository();
  const service = new DetectionCapabilityService(repository, {
    ttlMs: 30_000,
    now: () => now,
  });

  const [first, shared] = await Promise.all([
    service.loadDetectionContext(),
    service.loadDetectionContext(),
  ]);
  assert.equal(first, shared);
  assert.equal(repository.activeCalls, 1);
  assert.equal(repository.labelCalls, 1);

  const cached = await service.loadDetectionContext();
  assert.equal(cached, first);
  assert.equal(repository.activeCalls, 1);

  service.invalidate();
  const refreshed = await service.loadDetectionContext();
  assert.notEqual(refreshed, first);
  assert.equal(repository.activeCalls, 2);
  assert.equal(repository.labelCalls, 2);

  now += 31_000;
  await service.loadDetectionContext();
  assert.equal(repository.activeCalls, 3);
  assert.equal(repository.labelCalls, 3);

  console.log('Detection capability cache tests passed.');
}

void main();
