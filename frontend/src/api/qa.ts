/**
 * api/qa.ts — Gemini AI Assistant Q&A API (VS-QA-CHAT)
 */
import { apiClient } from './client';
import type { VideoClipInfo } from '../types';

export interface QAResponse {
  text: string;
  clip?: VideoClipInfo;
  sources?: string[];
  executionTimeMs?: number;
}

export async function askQA(
  query: string,
  history?: Array<{ role: 'user' | 'ai'; text: string }>
): Promise<QAResponse> {
  return apiClient.post<QAResponse>('/qa/query', {
    query,
    history,
  });
}
