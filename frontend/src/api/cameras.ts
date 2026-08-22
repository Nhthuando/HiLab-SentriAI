import { apiClient } from './client';

export interface CameraPlaybackState {
  cameraId: string;
  seekable: boolean;
  positionSeconds: number;
  durationSeconds: number;
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
