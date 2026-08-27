import type { ModelVersion, ObjectLabel, PrismaClient } from '@prisma/client';
import { prisma } from '../prisma/client';

export type ObjectLabelWithSampleCount = ObjectLabel & {
  _count: { samples: number };
};

/**
 * Read-side persistence boundary for the detection control plane.
 *
 * Capability routing deliberately receives only label metadata and an aggregate
 * sample count. It never reads individual samples and must not use the count to
 * decide whether a class is detectable.
 */
export interface DetectionControlRepository {
  findActiveModel(): Promise<ModelVersion | null>;
  listLabelsWithSampleCount(): Promise<ObjectLabelWithSampleCount[]>;
}

export class PrismaDetectionControlRepository implements DetectionControlRepository {
  constructor(private readonly client: PrismaClient = prisma) {}

  async findActiveModel(): Promise<ModelVersion | null> {
    const records = await this.client.modelVersion.findMany({
      where: { status: 'ACTIVE' },
      orderBy: { activatedAt: 'desc' },
      take: 1,
    });
    return records[0] ?? null;
  }

  async listLabelsWithSampleCount(): Promise<ObjectLabelWithSampleCount[]> {
    return this.client.objectLabel.findMany({
      include: {
        _count: {
          select: { samples: true },
        },
      },
      orderBy: { vietnameseName: 'asc' },
    });
  }
}
