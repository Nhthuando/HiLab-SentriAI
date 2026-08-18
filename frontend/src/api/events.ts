import { apiClient, API_BASE_URL } from './client';
import type { AreaEventsPage, GateEvent } from '../types';

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
  offset?: number;
  zoneId?: string;
  status?: 'OPEN' | 'CLOSED';
}): Promise<AreaEventsPage> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.set('limit', String(params.limit));
  if (params?.offset !== undefined) query.set('offset', String(params.offset));
  if (params?.zoneId) query.set('zone_id', params.zoneId);
  if (params?.status) query.set('status', params.status);

  const qs = query.toString() ? `?${query.toString()}` : '';
  return apiClient.get<AreaEventsPage>(`/events/area${qs}`);
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
  return `${baseUrl}/data/clips/${encodeURIComponent(cleanName)}`;
}
