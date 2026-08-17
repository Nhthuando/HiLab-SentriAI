/**
 * middleware/notFoundHandler.ts — 404 Route Not Found Handler
 */
import type { Request, Response } from 'express';
import { sendError } from '../utils/response';

export function notFoundHandler(req: Request, res: Response): void {
  sendError(
    res,
    404,
    'ROUTE_NOT_FOUND',
    `Cannot ${req.method} ${req.originalUrl}`
  );
}
