/**
 * routes/index.ts — Central /api/v1 REST Router Index
 *
 * Mounts all module routes under versioned prefix /api/v1:
 * - /api/v1/health
 * - /api/v1/vehicles      (VS-SETTINGS-VEHICLE)
 * - /api/v1/zones         (VS-SETTINGS-ZONE)
 * - /api/v1/labels        (VS-SETTINGS-LABEL)
 * - /api/v1/events/gate   (VS-GATE-LIVE)
 * - /api/v1/events/area   (VS-AREA-VIOLATION)
 * - /api/v1/qa            (VS-QA-CHAT)
 * - /api/v1/analytics     (VS-KPI-ANALYTICS)
 * - /api/v1/clips         (VS-QA-CHAT / Media stream)
 */
import { Router } from 'express';
import { healthRouter } from './health';
import { testErrorRouter } from './testError';

const apiRouter = Router();

// Mount Health check
apiRouter.use('/health', healthRouter);

// Mount Test Error router for API contract verification
apiRouter.use('/test-error', testErrorRouter);

// Downstream feature routes will be mounted here by their respective vertical slices
// e.g.:
// apiRouter.use('/vehicles', vehiclesRouter);
// apiRouter.use('/zones', zonesRouter);
// apiRouter.use('/labels', labelsRouter);
// apiRouter.use('/events', eventsRouter);
// apiRouter.use('/qa', qaRouter);
// apiRouter.use('/analytics', analyticsRouter);

export { apiRouter };
