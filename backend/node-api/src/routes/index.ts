/**
 * routes/index.ts — Central /api/v1 REST Router Index
 *
 * Mounts all module routes under versioned prefix /api/v1:
 * - /api/v1/health
 * - /api/v1/vehicles      (VS-SETTINGS-VEHICLE)
 * - /api/v1/zones         (VS-SETTINGS-ZONE)
 * - /api/v1/cameras       (VS-SETTINGS-ZONE)
 * - /api/v1/labels        (VS-SETTINGS-LABEL)
 * - /api/v1/samples       (VS-SETTINGS-LABEL)
 * - /api/v1/upload        (VS-SETTINGS-LABEL)
 * - /api/v1/events/gate   (VS-GATE-LIVE)
 * - /api/v1/events/area   (VS-AREA-VIOLATION)
 */
import { Router } from 'express';
import { camerasRouter } from './cameras';
import { eventsRouter } from './events';
import { healthRouter } from './health';
import { labelsRouter } from './labels';
import { samplesRouter } from './samples';
import { testErrorRouter } from './testError';
import { uploadRouter } from './upload';
import { vehiclesRouter } from './vehicles';
import { zonesRouter } from './zones';

const apiRouter = Router();

// Mount Health check
apiRouter.use('/health', healthRouter);

// Mount Test Error router for API contract verification
apiRouter.use('/test-error', testErrorRouter);

// Mount Registered Vehicles CRUD (VS-SETTINGS-VEHICLE)
apiRouter.use('/vehicles', vehiclesRouter);

// Mount Zones & Cameras (VS-SETTINGS-ZONE)
apiRouter.use('/zones', zonesRouter);
apiRouter.use('/cameras', camerasRouter);

// Mount Object Labels & Annotation Samples (VS-SETTINGS-LABEL)
apiRouter.use('/labels', labelsRouter);
apiRouter.use('/samples', samplesRouter);
apiRouter.use('/upload', uploadRouter);

// Mount Monitoring Events (VS-GATE-LIVE, VS-AREA-VIOLATION)
apiRouter.use('/events', eventsRouter);

export { apiRouter };
