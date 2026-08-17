/**
 * api/events.ts — Gate & Area Monitoring Events API (VS-GATE-LIVE, VS-AREA-VIOLATION)
 */
import { apiClient, API_BASE_URL } from './client';
import type { AreaEvent, GateEvent } from '../types';

export async function getGateEvents(params?: {
  limit?: number;
  cameraId?: string;
  plate?: string;
}): Promise<GateEvent[]> {
  const query = new URLSearchParams();
  if (params?.limit) query.set('limit', String(params.limit));
  if (params?.cameraId) query.set('camera_id', params.cameraId);
  if (params?.plate) query.set('plate', params.plate);

  const qs = query.toString() ? `?${query.toString()}` : '';
  return apiClient.get<GateEvent[]>(`/events/gate${qs}`);
}

export async function getAreaEvents(params?: {
  limit?: number;
  cameraId?: string;
  zoneId?: string;
}): Promise<AreaEvent[]> {
  const query = new URLSearchParams();
  if (params?.limit) query.set('limit', String(params.limit));
  if (params?.cameraId) query.set('camera_id', params.cameraId);
  if (params?.zoneId) query.set('zone_id', params.zoneId);

  const qs = query.toString() ? `?${query.toString()}` : '';
  return apiClient.get<AreaEvent[]>(`/events/area${qs}`);
}

export function getCropImageUrl(cropPathOrName?: string | null): string {
  if (!cropPathOrName) return '';
  if (cropPathOrName.startsWith('http') || cropPathOrName.startsWith('data:')) {
    return cropPathOrName;
  }
  const cleanName = cropPathOrName.replace(/^.*[\\/]/, '');
  const baseUrl = API_BASE_URL.replace(/\/api\/v1\/?$/, '');
  return `${baseUrl}/data/crops/${cleanName}`;
}

export function getClipUrl(clipPathOrName?: string | null): string {
  if (!clipPathOrName) return '';
  if (clipPathOrName.startsWith('http') || clipPathOrName.startsWith('data:')) {
    return clipPathOrName;
  }
  const cleanName = clipPathOrName.replace(/^.*[\\/]/, '');
  const baseUrl = API_BASE_URL.replace(/\/api\/v1\/?$/, '');
  return `${baseUrl}/data/clips/${cleanName}`;
}
