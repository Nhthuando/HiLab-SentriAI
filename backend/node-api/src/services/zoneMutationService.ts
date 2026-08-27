import type { Prisma, Zone } from '@prisma/client';
import type { ZoneMutationRepository } from '../repositories/ZoneMutationRepository';

function isPrismaRecordNotFound(error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'code' in error
    && (error as { code?: unknown }).code === 'P2025';
}

export class ZoneNotFoundError extends Error {
  constructor() {
    super('Zone was not found');
    this.name = 'ZoneNotFoundError';
  }
}

export class ZoneMutationService {
  constructor(private readonly repository: ZoneMutationRepository) {}

  async update(id: string, data: Prisma.ZoneUpdateInput): Promise<Zone> {
    try {
      return await this.repository.update(id, data);
    } catch (error) {
      if (isPrismaRecordNotFound(error)) throw new ZoneNotFoundError();
      throw error;
    }
  }

  async delete(id: string): Promise<void> {
    try {
      await this.repository.delete(id);
    } catch (error) {
      if (isPrismaRecordNotFound(error)) return;
      throw error;
    }
  }
}
