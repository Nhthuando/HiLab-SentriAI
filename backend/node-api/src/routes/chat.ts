import { Router, type Request, type Response } from 'express';
import { prisma } from '../prisma/client';
import { hydrateChatReference } from '../services/clipService';
import { sendError, sendNoContent, sendSuccess } from '../utils/response';

const chatRouter = Router();

chatRouter.get('/history', async (req: Request, res: Response) => {
  const rawLimit = req.query.limit;
  if (Array.isArray(rawLimit) || (rawLimit !== undefined && typeof rawLimit !== 'string')) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'limit must be a single integer');
  }
  const limit = rawLimit === undefined ? undefined : Number(rawLimit);
  if (limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 500)) {
    return sendError(res, 400, 'VALIDATION_ERROR', 'limit must be an integer between 1 and 500');
  }

  try {
    const rows = await prisma.chatMessage.findMany({
      orderBy: limit ? { createdAt: 'desc' } : { createdAt: 'asc' },
      ...(limit ? { take: limit } : {}),
    });
    if (limit) rows.reverse();
    const messages = await Promise.all(rows.map(async (row) => {
      const attachment = row.role === 'assistant'
        ? await hydrateChatReference(row.clipReference)
        : {};
      return {
        id: row.id,
        role: row.role,
        text: row.content,
        createdAt: row.createdAt.toISOString(),
        ...(attachment.clip ? { clip: attachment.clip } : {}),
        ...(attachment.evidence ? { evidence: attachment.evidence } : {}),
      };
    }));
    return sendSuccess(res, messages);
  } catch (error) {
    console.error('[chatRouter] Failed to load history:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to load chat history');
  }
});

chatRouter.delete('/history', async (_req: Request, res: Response) => {
  try {
    await prisma.chatMessage.deleteMany({});
    return sendNoContent(res);
  } catch (error) {
    console.error('[chatRouter] Failed to clear history:', error);
    return sendError(res, 500, 'INTERNAL_SERVER_ERROR', 'Failed to clear chat history');
  }
});

export { chatRouter };
