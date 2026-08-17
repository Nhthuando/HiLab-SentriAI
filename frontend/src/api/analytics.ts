/**
 * api/analytics.ts — KPI Analytics & Operations Metrics API (VS-KPI-ANALYTICS)
 */
import { apiClient } from './client';

export interface KPIData {
  gate: {
    totalScans: number;
    knownCount: number;
    strangerCount: number;
    unreadableCount: number;
    avgConfidence: number;
  };
  area: {
    totalViolations: number;
    activeViolations: number;
    resolvedViolations: number;
    mostViolatedZone?: string;
  };
  system: {
    activeStreams: number;
    streamFps: Record<string, number>;
    dbLatencyMs: number;
  };
}

export async function getKPIs(): Promise<KPIData> {
  return apiClient.get<KPIData>('/analytics/kpis');
}
