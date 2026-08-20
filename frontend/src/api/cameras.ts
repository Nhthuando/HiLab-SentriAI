/**
 * api/cameras.ts — Camera Settings & Control API
 */
import { apiClient } from './client';

export interface CameraConfig {
  cameraId: string;
  minConfidence: number; // e.g. 0.70
}

export async function getCameraConfig(cameraId: string = 'GATE-01'): Promise<CameraConfig> {
  return apiClient.get<CameraConfig>(`/cameras/${encodeURIComponent(cameraId)}/config`);
}

export async function updateCameraConfig(
  cameraId: string = 'GATE-01',
  config: Partial<CameraConfig>
): Promise<CameraConfig> {
  return apiClient.post<CameraConfig>(`/cameras/${encodeURIComponent(cameraId)}/config`, config);
}
