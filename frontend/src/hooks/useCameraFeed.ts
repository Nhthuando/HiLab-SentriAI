import { useState, useCallback } from 'react';
import { useWebSocket } from './useWebSocket';
import type { AreaZoneFeedDto } from '../types';

export interface BoundingBoxDetection {
  bbox: [number, number, number, number]; // [x1, y1, x2, y2]
  normalized_bbox?: [number, number, number, number];
  class: string;
  confidence: number;
  label?: string;
  trackId?: number | null;
  status?: 'KNOWN' | 'STRANGER' | 'VIOLATION' | 'ALLOWED' | 'NORMAL' | string;
  zoneMatches?: Array<{
    zoneId: string;
    zoneName: string;
    status: 'VIOLATION' | 'ALLOWED' | string;
  }>;
}

export interface FramePacket {
  type: 'frame';
  cameraId: string;
  timestamp: number;
  image: string; // base64 JPEG
  fps?: number;
  detections?: BoundingBoxDetection[];
  zones?: AreaZoneFeedDto[];
}

export interface StatusPacket {
  type: 'status';
  cameraId: string;
  status: 'ONLINE' | 'OFFLINE' | 'DISCONNECTED';
  timestamp: string;
  message?: string;
}

export type FeedMessage = FramePacket | StatusPacket;

export interface UseCameraFeedReturn {
  frameImage: string | null;
  detections: BoundingBoxDetection[];
  zones: AreaZoneFeedDto[];
  fps: number;
  isOnline: boolean;
  statusText: string;
  lastTimestamp: number | null;
  reconnect: () => void;
}

export function useCameraFeed(cameraId: string): UseCameraFeedReturn {
  const [frameImage, setFrameImage] = useState<string | null>(null);
  const [detections, setDetections] = useState<BoundingBoxDetection[]>([]);
  const [zones, setZones] = useState<AreaZoneFeedDto[]>([]);
  const [fps, setFps] = useState<number>(10.0);
  const [isOnline, setIsOnline] = useState<boolean>(true);
  const [statusText, setStatusText] = useState<string>('ONLINE');
  const [lastTimestamp, setLastTimestamp] = useState<number | null>(null);

  const canonicalPath =
    cameraId.toUpperCase().includes('GATE')
      ? '/ws/feed/gate'
      : '/ws/feed/area';

  const handleMessage = useCallback((msg: FeedMessage) => {
    if (!msg || typeof msg !== 'object') return;

    if (msg.type === 'frame') {
      const frame = msg as FramePacket;
      setFrameImage(frame.image);
      setDetections(frame.detections || []);
      if (frame.zones) {
        setZones(frame.zones);
      }
      if (frame.fps !== undefined) {
        setFps(frame.fps);
      }
      setLastTimestamp(frame.timestamp);
      setIsOnline(true);
      setStatusText('ONLINE');
    } else if (msg.type === 'status') {
      const st = msg as StatusPacket;
      if (st.status === 'OFFLINE' || st.status === 'DISCONNECTED') {
        setIsOnline(false);
        setStatusText('Mất kết nối'); // Matches AC-09 Vietnamese error label
      } else {
        setIsOnline(true);
        setStatusText('ONLINE');
      }
    }
  }, []);

  const { reconnect, isConnected } = useWebSocket<FeedMessage>({
    path: canonicalPath,
    onMessage: handleMessage,
    onClose: () => {
      setIsOnline(false);
      setStatusText('Mất kết nối');
    },
  });

  return {
    frameImage,
    detections,
    zones,
    fps,
    isOnline: isConnected && isOnline,
    statusText: isConnected && isOnline ? statusText : 'Mất kết nối',
    lastTimestamp,
    reconnect,
  };
}
