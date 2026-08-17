/**
 * api/health.ts — System Health Check API
 */
import { apiClient } from './client';

export interface HealthData {
  status: 'healthy' | 'degraded';
  service: string;
  version: string;
  database: {
    status: 'connected' | 'disconnected';
    engine: string;
  };
  websocket: {
    active_channels: number;
    subscribers: Record<string, number>;
  };
  uptime_seconds: number;
}

export async function getHealth(): Promise<HealthData> {
  return apiClient.get<HealthData>('/health');
}
