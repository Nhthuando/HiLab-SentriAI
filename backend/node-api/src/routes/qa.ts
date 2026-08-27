import { Router, type NextFunction, type Request, type Response } from 'express';
import { qaGeminiService, type QaGeminiService } from '../ai/gemini';
import { prisma } from '../prisma/client';
import { serializeChatReference } from '../services/clipService';
import { ValidationError } from '../utils/errors';
import { sendSuccess } from '../utils/response';

const MAX_QUERY_LENGTH = 1_000;

export function createQaRouter(service: Pick<QaGeminiService, 'answer'> = qaGeminiService): Router {
  const router = Router();

  router.post('/query', async (req: Request, res: Response, next: NextFunction) => {
    try {
      const query = typeof req.body?.query === 'string' ? req.body.query.trim() : '';
      if (!query) throw new ValidationError('query is required');
      if (query.length > MAX_QUERY_LENGTH) throw new ValidationError(`query must be at most ${MAX_QUERY_LENGTH} characters`);

      await prisma.chatMessage.create({ data: { role: 'user', content: query } });
      const answer = await service.answer(query);
      const message = await prisma.chatMessage.create({
        data: {
          role: 'assistant',
          content: answer.text,
          clipReference: serializeChatReference(answer.clip, answer.evidence),
        },
      });

      return sendSuccess(res, {
        id: message.id,
        role: 'assistant' as const,
        text: answer.text,
        ...(answer.clip ? { clip: answer.clip } : {}),
        ...(answer.evidence ? { evidence: answer.evidence } : {}),
        sources: answer.sources,
        executionTimeMs: answer.executionTimeMs,
        createdAt: message.createdAt.toISOString(),
      });
    } catch (error) {
      return next(error);
    }
  });

  return router;
}

export const qaRouter = createQaRouter();
