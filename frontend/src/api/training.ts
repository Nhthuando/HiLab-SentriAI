import { apiRequest } from './client';

export interface TrainingReadinessResponse {
  savedSamples: number;
  labelsWithSamples: number;
  sourceCount: number;
  excludedSamples: number;
  ready: boolean;
  profile: string | null;
  ignoredSamples: number;
  issues: string[];
  labelCoverage: Array<{
    label: string;
    baseClass: string;
    minimumSamples: number;
    minimumSources: number;
    savedSamples: number;
    sourceCount: number;
    splitCounts: { train: number; val: number; test: number };
    ready: boolean;
  }>;
  excluded: Array<{ id: string; reason: string }>;
}

export interface TrainingJobResponse {
  id: string;
  status: 'QUEUED' | 'RUNNING' | 'PAUSED_GPU' | 'EVALUATING' | 'SUCCEEDED' | 'FAILED';
  failureReason?: string | null;
  modelVersion?: { id: string; status: 'CANDIDATE' | 'ACTIVE' | 'INACTIVE' | 'REJECTED' } | null;
}

export const getTrainingReadiness = () => apiRequest<TrainingReadinessResponse>('/training/datasets/readiness?profile=YARD_VEHICLE_V1');
export const exportTrainingDataset = () => apiRequest<any>('/training/datasets/export', { method: 'POST', body: JSON.stringify({ profile: 'YARD_VEHICLE_V1' }) });
export const createTrainingJob = (datasetId: string) => apiRequest<TrainingJobResponse>('/training/jobs', { method: 'POST', body: JSON.stringify({ datasetId, baseModel: 'yolo11n.pt' }) });
export const startTrainingJob = (id: string) => apiRequest<{ id: string; status: string }>(`/training/jobs/${id}/start`, { method: 'POST' });
export const listTrainingJobs = () => apiRequest<TrainingJobResponse[]>('/training/jobs');
export const listModelVersions = () => apiRequest<any[]>('/training/jobs/versions');
export const useModelVersion = (id: string) => apiRequest(`/training/jobs/versions/${id}/use`, { method: 'POST' });
export const returnToBaseModel = () => apiRequest('/training/jobs/versions/return', { method: 'POST' });
