/**
 * api/zones.ts — Monitoring Zones Configuration API (VS-SETTINGS-ZONE)
 */
import { apiClient } from './client';
import type { PolygonZone } from '../types';

export interface ZoneRecord {
  id: string;
  cameraId: string;
  name: string;
  polygonPoints: Array<{ x: number; y: number }> | Array<[number, number]>;
  ruleType: 'PROHIBIT_SPECIFIED' | 'ALLOW_ONLY_SPECIFIED' | string;
  targetLabels: string[];
  isActive: boolean;
  color?: string;
  createdAt?: string;
  updatedAt?: string;
}

export async function getZones(cameraId?: string): Promise<PolygonZone[]> {
  const qs = cameraId ? `?camera_id=${encodeURIComponent(cameraId)}` : '';
  return apiClient.get<PolygonZone[]>(`/zones${qs}`);
}

export async function createZone(data: {
  cameraId: string;
  name: string;
  polygonPoints: Array<[number, number]> | Array<{ x: number; y: number }>;
  ruleType?: string;
  targetLabels?: string[];
  isActive?: boolean;
  color?: string;
  types?: Record<string, number>;
}): Promise<PolygonZone> {
  return apiClient.post<PolygonZone>('/zones', data);
}

export async function updateZone(
  id: string,
  data: Partial<PolygonZone> & {
    polygonPoints?: Array<[number, number]> | Array<{ x: number; y: number }>;
    ruleType?: string;
    targetLabels?: string[];
    isActive?: boolean;
  }
): Promise<PolygonZone> {
  return apiClient.put<PolygonZone>(`/zones/${id}`, data);
}

export async function deleteZone(id: string): Promise<{ id: string }> {
  return apiClient.delete<{ id: string }>(`/zones/${id}`);
}
