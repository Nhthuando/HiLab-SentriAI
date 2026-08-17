/**
 * routes/health.ts — System Health & Liveness Route
 */
import { Router } from 'express';
import { checkDatabaseConnection } from '../prisma/client';
import { channelManager } from '../ws';
import { sendSuccess } from '../utils/response';

const router = Router();

router.get('/', async (_req, res, next) => {
  try {
    const isDbConnected = await checkDatabaseConnection();
    const wsStats = channelManager.getStats();

    const healthData = {
      status: isDbConnected ? 'healthy' : 'degraded',
      service: 'sentriai-node-api',
      version: '0.1.0',
      database: {
        status: isDbConnected ? 'connected' : 'disconnected',
        engine: 'PostgreSQL (Neon)',
      },
      websocket: {
        active_channels: Object.keys(wsStats).length,
        subscribers: wsStats,
      },
      uptime_seconds: Math.round(process.uptime() * 100) / 100,
    };

    sendSuccess(res, healthData);
  } catch (err) {
    next(err);
  }
});

export const healthRouter = router;
