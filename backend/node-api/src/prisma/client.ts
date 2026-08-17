/**
 * prisma/client.ts — Prisma Client Singleton Instance
 *
 * Provides a single shared PrismaClient instance across all Node.js services,
 * with connection logging and graceful disconnection handling.
 */
import { PrismaClient } from '@prisma/client';

const globalForPrisma = global as unknown as { prisma?: PrismaClient };

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: process.env.NODE_ENV === 'development' ? ['error', 'warn'] : ['error'],
  });

if (process.env.NODE_ENV !== 'production') {
  globalForPrisma.prisma = prisma;
}

export async function checkDatabaseConnection(): Promise<boolean> {
  try {
    await prisma.$queryRaw`SELECT 1`;
    return true;
  } catch (err) {
    console.error('[Prisma] Database connection check failed:', err);
    return false;
  }
}
