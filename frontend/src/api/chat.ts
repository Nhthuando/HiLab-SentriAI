/**
 * api/chat.ts — Persistent Q&A chat history API (VS-QA-CHAT)
 */
import { apiClient } from './client';
import type { ActivityEvidence, VideoClipInfo } from '../types';

export interface ChatHistoryRecord {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  createdAt: string;
  clip?: VideoClipInfo;
  evidence?: ActivityEvidence;
}

export async function getChatHistory(limit = 200): Promise<ChatHistoryRecord[]> {
  return apiClient.get<ChatHistoryRecord[]>(`/chat/history?limit=${limit}`);
}

export async function clearChatHistory(): Promise<void> {
  await apiClient.delete<void>('/chat/history');
}
