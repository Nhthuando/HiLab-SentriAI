import { apiClient } from './client';
import type { PolygonZone } from '../types';

export type ZoneRuleType = 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED';

export interface ZoneRecord {
  id: string;
  cameraId: 'BAI-KIEM';
  name: string;
  polygonPoints: Array<{ x: number; y: number }>;
  ruleType: ZoneRuleType;
  targetLabels: string[];
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ZoneWriteInput {
  cameraId: 'BAI-KIEM';
  name: string;
  polygonPoints: Array<{ x: number; y: number }>;
  ruleType: ZoneRuleType;
  targetLabels: string[];
  isActive: boolean;
}

const ZONE_COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#f43f5e', '#a855f7', '#06b6d4'];

function getZoneColor(id: string): string {
  let hash = 0;
  for (let index = 0; index < id.length; index += 1) {
    hash = (hash << 5) - hash + id.charCodeAt(index);
    hash |= 0;
  }
  return ZONE_COLORS[Math.abs(hash) % ZONE_COLORS.length];
}

export function zoneRecordToView(
  record: ZoneRecord,
  availableLabels: string[],
): PolygonZone {
  const targeted = new Set(record.targetLabels.map((label) => label.toLocaleLowerCase()));
  const types: Record<string, number> = {};
  for (const label of availableLabels) {
    const isTargeted = targeted.has(label.toLocaleLowerCase());
    types[label] = record.ruleType === 'ALLOW_SPECIFIED'
      ? (isTargeted ? 1 : 0)
      : (isTargeted ? 0 : 1);
  }

  return {
    id: record.id,
    name: record.name,
    color: getZoneColor(record.id),
    points: record.polygonPoints.map((point) => [point.x * 100, point.y * 100]),
    types,
    ruleType: record.ruleType,
    targetLabels: record.targetLabels,
  };
}

export function zoneViewToWrite(
  zone: PolygonZone,
  availableLabels: string[],
): ZoneWriteInput {
  const allowedLabels = availableLabels.filter((label) => Boolean(zone.types[label]));
  const forbiddenLabels = availableLabels.filter((label) => !zone.types[label]);
  const useAllowRule = allowedLabels.length <= forbiddenLabels.length;

  return {
    cameraId: 'BAI-KIEM',
    name: zone.name.trim(),
    polygonPoints: zone.points.map(([x, y]) => ({ x: x / 100, y: y / 100 })),
    ruleType: useAllowRule ? 'ALLOW_SPECIFIED' : 'PROHIBIT_SPECIFIED',
    targetLabels: useAllowRule ? allowedLabels : forbiddenLabels,
    isActive: true,
  };
}

export async function getZones(): Promise<ZoneRecord[]> {
  return apiClient.get<ZoneRecord[]>('/zones?camera_id=BAI-KIEM');
}

export async function createZone(data: ZoneWriteInput): Promise<ZoneRecord> {
  return apiClient.post<ZoneRecord>('/zones', data);
}

export async function updateZone(
  id: string,
  data: Partial<Omit<ZoneWriteInput, 'cameraId'>>,
): Promise<ZoneRecord> {
  return apiClient.put<ZoneRecord>(`/zones/${encodeURIComponent(id)}`, data);
}

export async function deleteZone(id: string): Promise<void> {
  await apiClient.delete<undefined>(`/zones/${encodeURIComponent(id)}`);
}

export async function getAreaCameraSnapshot(): Promise<string> {
  const response = await apiClient.get<{ image: string }>('/cameras/BAI-KIEM/snapshot');
  return response.image;
}
