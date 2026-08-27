import {
  FunctionCallingConfigMode,
  GoogleGenAI,
  type Content,
  type FunctionCall,
} from '@google/genai';
import { AppError } from '../utils/errors';
import { QA_SYSTEM_PROMPT } from './prompts';
import { executeQaTool, QA_TOOL_DECLARATIONS, type QaToolExecution } from './tools';
import type { ActivityEvidence, ClipReference } from '../services/clipService';

const GEMINI_MODEL = 'gemini-3.5-flash-lite';
const GEMINI_TIMEOUT_MS = 15_000;
const MAX_TOOL_ROUNDS = 3;

export class GeminiTimeoutError extends AppError {
  constructor() {
    super('Gemini API timeout', 504, 'GEMINI_TIMEOUT');
  }
}

export class GeminiUnavailableError extends AppError {
  constructor() {
    super('Gemini API unavailable', 503, 'GEMINI_UNAVAILABLE');
  }
}

interface TransportResponse {
  text?: string;
  functionCalls?: FunctionCall[];
  modelContent?: Content;
}

export interface GeminiTransport {
  generate(contents: Content[], abortSignal: AbortSignal): Promise<TransportResponse>;
}

class GoogleGeminiTransport implements GeminiTransport {
  private readonly client: GoogleGenAI;

  constructor(apiKey: string) {
    this.client = new GoogleGenAI({ apiKey });
  }

  async generate(contents: Content[], abortSignal: AbortSignal): Promise<TransportResponse> {
    const response = await this.client.models.generateContent({
      model: GEMINI_MODEL,
      contents,
      config: {
        systemInstruction: QA_SYSTEM_PROMPT,
        temperature: 0.1,
        maxOutputTokens: 700,
        tools: [{ functionDeclarations: QA_TOOL_DECLARATIONS }],
        toolConfig: {
          functionCallingConfig: { mode: FunctionCallingConfigMode.VALIDATED },
        },
        abortSignal,
      },
    });
    return {
      text: response.text,
      functionCalls: response.functionCalls,
      modelContent: response.candidates?.[0]?.content,
    };
  }
}

export interface QaAnswer {
  text: string;
  clip?: ClipReference;
  evidence?: ActivityEvidence;
  sources: string[];
  executionTimeMs: number;
}

export class QaGeminiService {
  constructor(
    private readonly transport: GeminiTransport,
    private readonly toolExecutor: (name: string, args?: Record<string, unknown>) => Promise<QaToolExecution> = executeQaTool,
    private readonly timeoutMs = GEMINI_TIMEOUT_MS,
  ) {}

  async answer(query: string): Promise<QaAnswer> {
    const startedAt = Date.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    const contents: Content[] = [{ role: 'user', parts: [{ text: query }] }];
    const sources = new Set<string>();
    const clips = new Map<string, ClipReference>();
    let evidence: ActivityEvidence | undefined;

    try {
      for (let round = 0; round <= MAX_TOOL_ROUNDS; round += 1) {
        let response: TransportResponse;
        try {
          response = await this.transport.generate(contents, controller.signal);
        } catch (error) {
          if (controller.signal.aborted || (error instanceof Error && error.name === 'AbortError')) {
            throw new GeminiTimeoutError();
          }
          throw new GeminiUnavailableError();
        }

        const calls = response.functionCalls ?? [];
        if (calls.length === 0) {
          const text = response.text?.trim() || 'Không tìm thấy thông tin';
          return {
            text,
            ...(clips.size ? { clip: [...clips.values()][0] } : {}),
            ...(evidence ? { evidence } : {}),
            sources: [...sources],
            executionTimeMs: Date.now() - startedAt,
          };
        }
        if (round === MAX_TOOL_ROUNDS || !response.modelContent) {
          throw new GeminiUnavailableError();
        }

        contents.push(response.modelContent);
        const resultParts = [];
        for (const call of calls) {
          if (!call.name) throw new GeminiUnavailableError();
          const execution = await this.toolExecutor(call.name, call.args ?? {});
          sources.add(execution.name);
          for (const clip of execution.clips) clips.set(`${clip.eventType}:${clip.eventId}`, clip);
          evidence ??= execution.evidence;
          resultParts.push({
            functionResponse: {
              id: call.id,
              name: call.name,
              response: { output: execution.result },
            },
          });
        }
        contents.push({ role: 'user', parts: resultParts });
        if (controller.signal.aborted) throw new GeminiTimeoutError();
      }
      throw new GeminiUnavailableError();
    } finally {
      clearTimeout(timeout);
    }
  }
}

function createDefaultService(): QaGeminiService {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    return new QaGeminiService({
      async generate() {
        throw new GeminiUnavailableError();
      },
    });
  }
  return createGoogleQaGeminiService(apiKey);
}

export function createGoogleQaGeminiService(
  apiKey: string,
  toolExecutor: (name: string, args?: Record<string, unknown>) => Promise<QaToolExecution> = executeQaTool,
): QaGeminiService {
  return new QaGeminiService(new GoogleGeminiTransport(apiKey), toolExecutor);
}

export const qaGeminiService = createDefaultService();
export { GEMINI_MODEL, GEMINI_TIMEOUT_MS };
