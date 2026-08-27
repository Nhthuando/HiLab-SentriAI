/**
 * Camera playback, preview, settings, and control API.
 */
import { apiClient } from './client';

export interface CameraPlaybackState {
  cameraId: string;
  seekable: boolean;
  positionSeconds: number;
  durationSeconds: number;
  positionMs?: number;
  durationMs?: number;
}

export interface CameraConfig {
  cameraId: string;
  minConfidence: number;
}

export function getCameraPlayback(cameraId: string): Promise<CameraPlaybackState> {
  return apiClient.get<CameraPlaybackState>(`/cameras/${encodeURIComponent(cameraId)}/playback`);
}

export function seekCameraPlayback(cameraId: string, positionSeconds: number): Promise<CameraPlaybackState> {
  return apiClient.post<CameraPlaybackState>(`/cameras/${encodeURIComponent(cameraId)}/playback`, { positionSeconds });
}

export function getCameraPlaybackPreview(cameraId: string, positionSeconds: number): Promise<{ image: string }> {
  return apiClient.get<{ image: string }>(`/cameras/${encodeURIComponent(cameraId)}/playback/preview?positionSeconds=${encodeURIComponent(String(positionSeconds))}`);
}

export function getCameraConfig(cameraId: string = 'GATE-01'): Promise<CameraConfig> {
  return apiClient.get<CameraConfig>(`/cameras/${encodeURIComponent(cameraId)}/config`);
}

export function updateCameraConfig(
  cameraId: string = 'GATE-01',
  config: Partial<CameraConfig>,
): Promise<CameraConfig> {
  return apiClient.post<CameraConfig>(`/cameras/${encodeURIComponent(cameraId)}/config`, config);
}
