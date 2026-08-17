/**
 * middleware/errorHandler.ts — Global Express Error Handling Middleware
 *
 * Catches all synchronous and asynchronous errors across route handlers,
 * maps Prisma ORM exceptions to clean HTTP status codes, and returns
 * standard error JSON responses.
 */
import type { NextFunction, Request, Response } from 'express';
import { Prisma } from '@prisma/client';
import { AppError } from '../utils/errors';
import { sendError } from '../utils/response';

export function errorHandler(
  err: Error | AppError | Prisma.PrismaClientKnownRequestError,
  _req: Request,
  res: Response,
  _next: NextFunction
): void {
  // 1. Custom Application Domain Errors
  if (err instanceof AppError) {
    sendError(res, err.statusCode, err.code, err.message, err.details);
    return;
  }

  // 2. Body Parser Malformed JSON Syntax Errors
  if (err instanceof SyntaxError && 'status' in err && (err as { status?: number }).status === 400) {
    sendError(res, 400, 'INVALID_JSON', 'Malformed JSON in request body');
    return;
  }

  // 3. Prisma Database Errors
  if (err instanceof Prisma.PrismaClientKnownRequestError) {
    // P2002: Unique constraint failed
    if (err.code === 'P2002') {
      const target = (err.meta?.target as string[]) || 'field';
      const targetStr = Array.isArray(target) ? target.join(', ') : String(target);
      sendError(
        res,
        409,
        'CONFLICT',
        `A record with this ${targetStr} already exists.`,
        { target }
      );
      return;
    }

    // P2025: Record not found
    if (err.code === 'P2025') {
      sendError(
        res,
        404,
        'NOT_FOUND',
        (err.meta?.cause as string) || 'Requested record was not found.'
      );
      return;
    }

    // P2003: Foreign key constraint violation
    if (err.code === 'P2003') {
      sendError(
        res,
        400,
        'FOREIGN_KEY_VIOLATION',
        'Foreign key constraint violation. Referenced record does not exist or cannot be deleted.',
        { field: err.meta?.field_name }
      );
      return;
    }

    sendError(res, 500, `DATABASE_ERROR_${err.code}`, 'A database error occurred.', { code: err.code });
    return;
  }

  if (err instanceof Prisma.PrismaClientValidationError) {
    sendError(res, 400, 'DATABASE_VALIDATION_ERROR', 'Invalid database query parameters or payload types.');
    return;
  }

  // 4. Generic Unhandled Internal Server Errors
  console.error('[Unhandled Server Error]:', err);
  const message = process.env.NODE_ENV === 'production' ? 'An unexpected server error occurred.' : err.message;
  sendError(res, 500, 'INTERNAL_SERVER_ERROR', message);
}
