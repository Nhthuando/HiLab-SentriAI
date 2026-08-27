/**
 * api/qa.ts — Gemini AI Assistant Q&A API (VS-QA-CHAT)
 */
import { apiClient } from './client';
import type { ActivityEvidence, VideoClipInfo } from '../types';

export interface QAResponse {
  id: string;
  role: 'assistant';
  text: string;
  clip?: VideoClipInfo;
  evidence?: ActivityEvidence;
  sources: string[];
  executionTimeMs: number;
  createdAt: string;
}

export async function askQA(query: string): Promise<QAResponse> {
  return apiClient.post<QAResponse>('/qa/query', { query });
}
