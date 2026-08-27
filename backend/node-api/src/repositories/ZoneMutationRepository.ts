import type { Prisma, PrismaClient, Zone } from '@prisma/client';
import { prisma } from '../prisma/client';

export interface ZoneMutationRepository {
  update(id: string, data: Prisma.ZoneUpdateInput): Promise<Zone>;
  delete(id: string): Promise<void>;
}

export class PrismaZoneMutationRepository implements ZoneMutationRepository {
  constructor(private readonly client: PrismaClient = prisma) {}

  update(id: string, data: Prisma.ZoneUpdateInput): Promise<Zone> {
    return this.client.zone.update({ where: { id }, data });
  }

  async delete(id: string): Promise<void> {
    await this.client.zone.delete({ where: { id } });
  }
}
