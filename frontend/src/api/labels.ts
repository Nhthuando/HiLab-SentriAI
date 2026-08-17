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
  baseClass: string;
  tint?: string;
  kind?: 'xe' | 'nguoi';
}): Promise<ObjectLabel> {
  return apiClient.post<ObjectLabel>('/labels', data);
}

export async function saveAnnotationSamples(
  samples: AnnotationSample[]
): Promise<{ count: number }> {
  return apiClient.post<{ count: number }>('/samples/batch', { samples });
}
