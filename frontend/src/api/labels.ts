/**
 * api/labels.ts — Object Labels & Annotation Samples API (VS-SETTINGS-LABEL)
 */
import { apiClient } from './client';
import type { AnnotationSample, ObjectLabel } from '../types';

export interface LabelRecord {
  id: string;
  vietnameseName: string;
  baseClass: string;
  tint?: string;
  samples?: number;
  createdAt?: string;
  updatedAt?: string;
}

export async function getLabels(): Promise<ObjectLabel[]> {
  return apiClient.get<ObjectLabel[]>('/labels');
}

export async function createLabel(data: {
  vietnameseName: string;
  baseClass?: string;
  tint?: string;
  kind?: 'xe' | 'nguoi';
  name?: string;
}): Promise<ObjectLabel> {
  const payload = {
    vietnameseName: data.vietnameseName || data.name || '',
    baseClass: data.baseClass || (data.kind === 'nguoi' ? 'person' : 'car'),
    tint: data.tint,
    kind: data.kind,
  };
  return apiClient.post<ObjectLabel>('/labels', payload);
}

export async function updateLabel(
  id: string,
  data: {
    vietnameseName?: string;
    name?: string;
    baseClass?: string;
    tint?: string;
    kind?: 'xe' | 'nguoi';
  }
): Promise<ObjectLabel> {
  const payload = {
    vietnameseName: data.vietnameseName || data.name,
    baseClass: data.baseClass,
    tint: data.tint,
    kind: data.kind,
  };
  return apiClient.put<ObjectLabel>(`/labels/${id}`, payload);
}

export async function deleteLabel(id: string): Promise<void> {
  return apiClient.delete<void>(`/labels/${id}`);
}

export async function getAnnotationSamples(): Promise<AnnotationSample[]> {
  return apiClient.get<AnnotationSample[]>('/samples');
}

export async function saveAnnotationSamples(
  samples: AnnotationSample[]
): Promise<{ count: number }> {
  return apiClient.post<{ count: number }>('/samples/batch', { samples });
}

export async function uploadLabelImage(data: {
  image: string;
  filename?: string;
}): Promise<{ path: string; url: string }> {
  return apiClient.post<{ path: string; url: string }>('/upload/image', data);
}

export async function getMediaSources(): Promise<any[]> {
  return apiClient.get<any[]>('/upload/media');
}

export async function uploadMediaSource(data: {
  data: string;
  filename: string;
  kind?: 'img' | 'video';
  thumbnail?: string;
}): Promise<any> {
  return apiClient.post<any>('/upload/media', data);
}

export async function deleteMediaSource(filename: string): Promise<void> {
  return apiClient.delete<void>(`/upload/media/${filename}`);
}

