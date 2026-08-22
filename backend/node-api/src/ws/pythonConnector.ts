/**
 * pythonConnector.ts — Outbound WebSocket Client Connecting to Python AI Worker
 *
 * Connects to Python worker WebSocket server (localhost:8001), receives real-time
 * video frames and detection events, and relays them to channelManager.
 * Automatically attempts reconnection with backoff if Python worker is offline.
 */
import WebSocket, { RawData } from 'ws';
import { channelManager } from './channels';
import type { WsMessage } from './types';

export class PythonWorkerConnector {
  private wsUrl: string;
  private ws: WebSocket | null = null;
  private isConnecting = false;
  private isStopped = false;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private backoffMs = 1000;
  private maxBackoffMs = 10000;

  constructor(wsUrl?: string) {
    this.wsUrl = wsUrl || process.env.PYTHON_WS_URL || 'ws://localhost:8001';
  }

  /**
   * Start connecting to Python AI Worker.
   */
  public start(): void {
    this.isStopped = false;
    this.connect();
  }

  /**
   * Stop connector and cancel reconnection timers.
   */
  public stop(): void {
    this.isStopped = true;
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // ignore
      }
      this.ws = null;
    }
  }

  public isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  /** Tell the Python worker whether a camera currently has a live-feed viewer. */
  public async setCameraActive(cameraId: string, active: boolean): Promise<void> {
    const httpBaseUrl = (process.env.PYTHON_HTTP_URL || this.wsUrl).replace(/^ws/, 'http').replace(/\/+$/, '');
    try {
      const response = await fetch(`${httpBaseUrl}/cameras/${encodeURIComponent(cameraId)}/activation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active }),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      console.warn(`[PythonConnector] Could not ${active ? 'activate' : 'pause'} ${cameraId}:`, err);
    }
  }

  private connect(): void {
    if (this.isStopped || this.isConnecting || this.isConnected()) {
      return;
    }

    this.isConnecting = true;
    const targetUrl = `${this.wsUrl}/ws/hub`;
    console.log(`[PythonConnector] Connecting to Python AI Worker at ${targetUrl}...`);

    try {
      this.ws = new WebSocket(targetUrl);

      this.ws.on('open', () => {
        this.isConnecting = false;
        this.backoffMs = 1000; // Reset backoff
        console.log(`[PythonConnector] Connected to Python AI Worker at ${targetUrl}`);
        channelManager.broadcastStatus('GATE-01', 'ONLINE');
        channelManager.broadcastStatus('BAI-KIEM', 'ONLINE');
      });

      this.ws.on('message', (raw: RawData) => {
        this.handleMessage(raw);
      });

      this.ws.on('close', (code, reason) => {
        this.isConnecting = false;
        this.ws = null;
        console.log(`[PythonConnector] Disconnected from Python Worker (${code}: ${reason.toString() || 'no reason'})`);
        channelManager.broadcastStatus('GATE-01', 'DISCONNECTED');
        channelManager.broadcastStatus('BAI-KIEM', 'DISCONNECTED');
        this.scheduleReconnect();
      });

      this.ws.on('error', (err) => {
        this.isConnecting = false;
        // Normal if Python worker isn't started yet during standalone node API runs
        console.warn(`[PythonConnector] Connection error with Python Worker (${err.message}). Retrying in ${this.backoffMs}ms...`);
        if (this.ws) {
          try {
            this.ws.close();
          } catch {
            // ignore
          }
          this.ws = null;
        }
        this.scheduleReconnect();
      });
    } catch (err) {
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.isStopped || this.reconnectTimeout) {
      return;
    }
    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.backoffMs = Math.min(this.backoffMs * 1.5, this.maxBackoffMs);
      this.connect();
    }, this.backoffMs);
  }

  private handleMessage(raw: RawData): void {
    try {
      let msg: WsMessage;
      if (typeof raw === 'string') {
        msg = JSON.parse(raw);
      } else if (Buffer.isBuffer(raw)) {
        // Binary or JSON buffer
        try {
          msg = JSON.parse(raw.toString('utf8'));
        } catch {
          // If pure binary JPEG frame without JSON envelope, handle or ignore
          return;
        }
      } else {
        return;
      }

      // Dispatch according to message type
      if (msg.type === 'frame' && 'cameraId' in msg) {
        channelManager.broadcastFeed(String(msg.cameraId), msg as any);
      } else if (msg.type === 'gate_event') {
        channelManager.broadcastGateEvent(msg);
      } else if (msg.type === 'zone_violation') {
        channelManager.broadcastAreaEvent(msg);
      } else if (msg.type === 'alert') {
        channelManager.broadcastAlert(msg);
      } else if (msg.type === 'status' && 'cameraId' in msg) {
        const rawStatus = String((msg as any).status ?? 'ONLINE') as 'ONLINE' | 'OFFLINE' | 'DISCONNECTED';
        const rawMessage = (msg as any).message ? String((msg as any).message) : undefined;
        channelManager.broadcastStatus(String(msg.cameraId), rawStatus, rawMessage);
      }
    } catch (err) {
      console.error('[PythonConnector] Error processing message from Python worker:', err);
    }
  }
}

export const pythonConnector = new PythonWorkerConnector();
