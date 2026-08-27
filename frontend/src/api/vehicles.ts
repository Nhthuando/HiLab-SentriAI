/**
 * api/vehicles.ts — Registered Vehicles Management API (VS-SETTINGS-VEHICLE)
 */
import { apiClient } from './client';
import type { Vehicle } from '../types';

export interface VehicleRecord {
  id: string;
  plateNumber: string;
  status: 'KNOWN' | 'STRANGER';
  note?: string | null;
  createdAt: string;
  updatedAt: string;
  cropPath?: string | null;
}

export async function getVehicles(params?: {
  type?: string;
  status?: string;
  search?: string;
  page?: number;
  limit?: number;
}): Promise<Vehicle[]> {
  const query = new URLSearchParams();
  if (params?.type) query.set('type', params.type);
  if (params?.status) query.set('status', params.status);
  if (params?.search) query.set('search', params.search);
  if (params?.page) query.set('page', String(params.page));
  if (params?.limit) query.set('limit', String(params.limit));

  const qs = query.toString() ? `?${query.toString()}` : '';
  return apiClient.get<Vehicle[]>(`/vehicles${qs}`);
}

export async function updateVehicleStatus(
  plateNumber: string,
  status: 'KNOWN' | 'STRANGER' | 'quen' | 'la'
): Promise<Vehicle> {
  const canonicalStatus =
    status === 'quen' || status === 'KNOWN' ? 'KNOWN' : 'STRANGER';

  return apiClient.patch<Vehicle>(`/vehicles/${encodeURIComponent(plateNumber)}/status`, {
    status: canonicalStatus,
  });
}

export async function registerVehicle(data: {
  plateNumber: string;
  status?: 'KNOWN' | 'STRANGER';
  note?: string;
}): Promise<VehicleRecord> {
  return apiClient.post<VehicleRecord>('/vehicles', data);
}

export async function deleteVehicle(idOrPlate: string): Promise<void> {
  return apiClient.delete<void>(`/vehicles/${encodeURIComponent(idOrPlate)}`);
}

export async function deleteVehicles(plates: string[]): Promise<{ deleted: number }> {
  return apiClient.post<{ deleted: number }>('/vehicles/bulk-delete', { plates });
}

export async function resetDemoData(): Promise<{ deletedEvents: number; deletedVehicles: number }> {
  return apiClient.post<{ deletedEvents: number; deletedVehicles: number }>('/vehicles/reset-demo', {});
}
