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
import { areaEventsRouter } from './areaEvents';
import { camerasRouter } from './cameras';
import { healthRouter } from './health';
import { testErrorRouter } from './testError';
import { zonesRouter } from './zones';

const apiRouter = Router();

// Mount Health check
apiRouter.use('/health', healthRouter);

// Mount Test Error router for API contract verification
apiRouter.use('/test-error', testErrorRouter);

// Mount VS-AREA-VIOLATION events router
apiRouter.use('/events/area', areaEventsRouter);

// Mount VS-SETTINGS-ZONE routes (BAI-KIEM only)
apiRouter.use('/zones', zonesRouter);
apiRouter.use('/cameras', camerasRouter);

// Downstream feature routes will be mounted here by their respective vertical slices
// e.g.:
// apiRouter.use('/vehicles', vehiclesRouter);
// apiRouter.use('/labels', labelsRouter);
// apiRouter.use('/events/gate', gateEventsRouter);
// apiRouter.use('/qa', qaRouter);
// apiRouter.use('/analytics', analyticsRouter);

export { apiRouter };
