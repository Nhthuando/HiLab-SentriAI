/**
 * channels.ts — Channel Subscription & Broadcasting Manager
 *
 * Manages subscriber sets for camera live feeds, event streams, and alerts.
 */
import { WebSocket } from 'ws';
import type {
  AlertMessage,
  AreaEventMessage,
  CameraId,
  ChannelName,
  ExtendedWebSocket,
  FrameMessage,
  GateEventMessage,
  StatusMessage,
  WsMessage,
} from './types';

export class ChannelManager {
  // Mapping of channel name -> Set of subscriber sockets
  private channels = new Map<string, Set<ExtendedWebSocket>>();

  /**
   * Normalize camera identifiers to canonical IDs (GATE-01, BAI-KIEM).
   */
  public canonicalCameraId(rawId: string): CameraId {
    const norm = rawId.trim().toUpperCase();
    if (norm === 'GATE' || norm === 'GATE-01' || norm === 'GATE_01' || norm === 'GATE1') {
      return 'GATE-01';
    }
    if (norm === 'AREA' || norm === 'BAI-KIEM' || norm === 'BAI_KIEM' || norm === 'BAIKIEM') {
      return 'BAI-KIEM';
    }
    return norm;
  }

  /**
   * Normalize channel name based on path or direct name.
   */
  public canonicalChannelName(rawName: string): ChannelName {
    const trimmed = rawName.trim();
    if (trimmed.startsWith('feed:')) {
      const cam = trimmed.slice(5);
      return `feed:${this.canonicalCameraId(cam)}`;
    }
    if (trimmed.startsWith('events:')) {
      const sub = trimmed.slice(7).toLowerCase();
      if (sub === 'gate' || sub === 'gate-01') return 'events:gate';
      if (sub === 'area' || sub === 'bai-kiem') return 'events:area';
      return `events:${sub}`;
    }
    if (trimmed === 'alerts' || trimmed === 'alert') {
      return 'alerts';
    }
    return trimmed;
  }

  /**
   * Subscribe a WebSocket client to a given channel.
   */
  public subscribe(channel: string, ws: ExtendedWebSocket): void {
    const canonical = this.canonicalChannelName(channel);
    if (!this.channels.has(canonical)) {
      this.channels.set(canonical, new Set());
    }
    const set = this.channels.get(canonical)!;
    set.add(ws);

    if (!ws.channels) {
      ws.channels = new Set();
    }
    ws.channels.add(canonical);
  }

  /**
   * Unsubscribe a WebSocket client from a given channel.
   */
  public unsubscribe(channel: string, ws: ExtendedWebSocket): void {
    const canonical = this.canonicalChannelName(channel);
    const set = this.channels.get(canonical);
    if (set) {
      set.delete(ws);
      if (set.size === 0) {
        this.channels.delete(canonical);
      }
    }
    if (ws.channels) {
      ws.channels.delete(canonical);
    }
  }

  /**
   * Unsubscribe a WebSocket client from all subscribed channels.
   */
  public unsubscribeAll(ws: ExtendedWebSocket): void {
    if (ws.channels) {
      for (const ch of ws.channels) {
        const set = this.channels.get(ch);
        if (set) {
          set.delete(ws);
          if (set.size === 0) {
            this.channels.delete(ch);
          }
        }
      }
      ws.channels.clear();
    }
  }

  /**
   * Broadcast a payload to all active subscribers on a channel.
   * Returns the count of clients successfully sent to.
   */
  public broadcast(channel: string, data: WsMessage | string | Buffer): number {
    const canonical = this.canonicalChannelName(channel);
    const subscribers = this.channels.get(canonical);
    if (!subscribers || subscribers.size === 0) {
      return 0;
    }

    const payload = typeof data === 'string' || Buffer.isBuffer(data) ? data : JSON.stringify(data);
    let sentCount = 0;

    for (const ws of subscribers) {
      if (ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(payload);
          sentCount++;
        } catch (err) {
          console.error(`[WS Channel] Error sending to subscriber on ${canonical}:`, err);
        }
      }
    }
    return sentCount;
  }

  /**
   * Convenience broadcaster for camera frame streams.
   */
  public broadcastFeed(cameraId: string, frame: FrameMessage | Buffer | string): number {
    const canonicalCam = this.canonicalCameraId(cameraId);
    return this.broadcast(`feed:${canonicalCam}`, frame);
  }

  /**
   * Convenience broadcaster for Gate events.
   */
  public broadcastGateEvent(event: GateEventMessage | object): number {
    const payload = 'type' in event ? event : { type: 'gate_event', ...event };
    return this.broadcast('events:gate', payload as WsMessage);
  }

  /**
   * Convenience broadcaster for Area violation events.
   */
  public broadcastAreaEvent(event: AreaEventMessage | object): number {
    const payload = 'type' in event ? event : { type: 'zone_violation', ...event };
    return this.broadcast('events:area', payload as WsMessage);
  }

  /**
   * Convenience broadcaster for Urgent Alerts.
   */
  public broadcastAlert(alert: AlertMessage | object): number {
    const payload = 'type' in alert ? alert : { type: 'alert', ...alert };
    return this.broadcast('alerts', payload as WsMessage);
  }

  /**
   * Convenience broadcaster for Camera Status (online/offline).
   */
  public broadcastStatus(cameraId: string, status: 'ONLINE' | 'OFFLINE' | 'DISCONNECTED', message?: string): number {
    const canonicalCam = this.canonicalCameraId(cameraId);
    const statusMsg: StatusMessage = {
      type: 'status',
      cameraId: canonicalCam,
      status,
      timestamp: new Date().toISOString(),
      message,
    };
    // Send to both feed channel and general alerts
    const c1 = this.broadcast(`feed:${canonicalCam}`, statusMsg);
    const c2 = this.broadcast('alerts', statusMsg);
    return c1 + c2;
  }

  /**
   * Get summary statistics of active channels and subscriber counts.
   */
  public getStats(): Record<string, number> {
    const stats: Record<string, number> = {};
    for (const [ch, set] of this.channels.entries()) {
      stats[ch] = set.size;
    }
    return stats;
  }
}

// Global default instance
export const channelManager = new ChannelManager();
