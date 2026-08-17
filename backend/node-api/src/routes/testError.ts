/**
 * routes/testError.ts — Test Error Triggers for Contract Testing
 */
import { Router } from 'express';
import { BadRequestError, ConflictError, NotFoundError, ValidationError } from '../utils/errors';

const router = Router();

router.get('/bad-request', () => {
  throw new BadRequestError('Test bad request error', { field: 'plate_number' });
});

router.get('/conflict', () => {
  throw new ConflictError('Test conflict error', { target: ['plate_number'] });
});

router.get('/not-found', () => {
  throw new NotFoundError('Test not found error');
});

router.get('/validation', () => {
  throw new ValidationError('Test validation error', { errors: ['Invalid email format'] });
});

export const testErrorRouter = router;
