/**
 * utils/response.ts — Standard API Response Envelope Helpers
 *
 * Enforces unified response schema across all SentriAI REST endpoints:
 * Success: { success: true, data: T, timestamp: string }
 * Error:   { success: false, error: { code, message, details }, timestamp: string }
 */
import type { Response } from 'express';

export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: unknown;
  };
  timestamp: string;
}

/**
 * Send standard 200/2xx success JSON response.
 */
export function sendSuccess<T>(res: Response, data: T, statusCode = 200): Response {
  const body: ApiResponse<T> = {
    success: true,
    data,
    timestamp: new Date().toISOString(),
  };
  return res.status(statusCode).json(body);
}

/**
 * Send standard 201 Created JSON response.
 */
export function sendCreated<T>(res: Response, data: T): Response {
  return sendSuccess(res, data, 201);
}

/**
 * Send standard 204 No Content response.
 */
export function sendNoContent(res: Response): Response {
  return res.status(204).send();
}

/**
 * Send standard error JSON response.
 */
export function sendError(
  res: Response,
  statusCode: number,
  code: string,
  message: string,
  details?: unknown
): Response {
  const body: ApiResponse = {
    success: false,
    error: {
      code,
      message,
      ...(details !== undefined ? { details } : {}),
    },
    timestamp: new Date().toISOString(),
  };
  return res.status(statusCode).json(body);
}
