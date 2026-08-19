/**
 * types.ts — Type definitions for SentriAI WebSocket Proxy
 */
import type { WebSocket } from 'ws';

export type CameraId = 'GATE-01' | 'BAI-KIEM' | string;

export type ChannelName =
  | 'feed:GATE-01'
  | 'feed:BAI-KIEM'
  | 'events:gate'
  | 'events:area'
  | 'alerts'
  | string;

export interface AreaZoneMatch {
  zoneId: string;
  zoneName: string;
  status: 'VIOLATION' | 'ALLOWED' | string;
}

export interface AreaZoneFeedDto {
  id: string;
  name: string;
  polygon: Array<{ x: number; y: number }> | Array<[number, number]>;
  ruleType: 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED' | string;
  targetLabels: string[];
}

export interface DetectionBox {
  bbox: [number, number, number, number]; // [x1, y1, x2, y2]
  normalized_bbox?: [number, number, number, number];
  class: string;
  confidence: number;
  label?: string;
  trackId?: number | null;
  status?: 'KNOWN' | 'STRANGER' | 'VIOLATION' | 'ALLOWED' | 'NORMAL' | string;
  zoneMatches?: AreaZoneMatch[];
}

export interface FrameMessage {
  type: 'frame';
  cameraId: CameraId;
  timestamp: number; // Unix timestamp in ms
  image: string; // Base64 JPEG or data URL
  fps?: number;
  detections?: DetectionBox[];
  zones?: AreaZoneFeedDto[];
}

export interface GateEventMessage {
  type: 'gate_event';
  id: string;
  cameraId: CameraId;
  lane: 'IN_1' | 'IN_2' | string;
  licensePlate: string;
  status: 'KNOWN' | 'STRANGER' | string;
  confidence: number;
  cropUrl?: string | null;
  clipUrl?: string | null;
  timestamp: string;
}

export interface AreaEventMessage {
  type: 'zone_violation';
  action?: 'STARTED' | 'ENDED';
  id: string;
  cameraId: CameraId;
  zoneId: string;
  zoneName?: string;
  objectLabel: string;
  status: 'OPEN' | 'CLOSED' | string;
  enteredAt: string;
  exitedAt?: string | null;
  durationSeconds?: number | null;
  clipUrl?: string | null;
}

export interface AlertMessage {
  type: 'alert';
  level: 'info' | 'warning' | 'critical';
  title: string;
  message: string;
  cameraId?: CameraId;
  timestamp: string;
  data?: Record<string, unknown>;
}

export interface StatusMessage {
  type: 'status';
  cameraId: CameraId;
  status: 'ONLINE' | 'OFFLINE' | 'DISCONNECTED';
  timestamp: string;
  message?: string;
}

export type WsMessage =
  | FrameMessage
  | GateEventMessage
  | AreaEventMessage
  | AlertMessage
  | StatusMessage
  | { type: string; [key: string]: unknown };

export interface ExtendedWebSocket extends WebSocket {
  isAlive?: boolean;
  channels?: Set<string>;
  role?: 'subscriber' | 'publisher';
  clientIp?: string;
}
