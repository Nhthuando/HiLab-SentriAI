import type { AreaClipStatus } from '../types';
import { apiClient } from './client';

export interface AreaActivityClipState {
  activityId: string;
  status: AreaClipStatus;
  clipId: string | null;
  clipUrl: string | null;
  message?: string;
}

export function requestAreaActivityClip(activityId: string): Promise<AreaActivityClipState> {
  return apiClient.post<AreaActivityClipState>(`/area-activities/${encodeURIComponent(activityId)}/clip`, {});
}

export function getAreaActivityClipStatus(activityId: string): Promise<AreaActivityClipState> {
  return apiClient.get<AreaActivityClipState>(`/area-activities/${encodeURIComponent(activityId)}/clip`);
}
