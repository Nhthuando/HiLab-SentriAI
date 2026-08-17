/**
 * server.ts — Node.js WebSocket Proxy Server
 *
 * Attaches to HTTP server, routes path-based connections to channels,
 * and manages publisher and subscriber sockets.
 */
import type { IncomingMessage } from 'http';
import type { Server as HttpServer } from 'http';
import { WebSocketServer, WebSocket, RawData } from 'ws';
import { channelManager } from './channels';
import type { ExtendedWebSocket, WsMessage } from './types';

export class SentriWebSocketServer {
  private wss: WebSocketServer;
  private pingInterval: NodeJS.Timeout | null = null;

  constructor(server: HttpServer) {
    // Create standalone WebSocketServer to manually handle upgrades
    this.wss = new WebSocketServer({ noServer: true });

    // Handle HTTP Upgrade requests
    server.on('upgrade', (request: IncomingMessage, socket, head) => {
      const pathname = this.getPathname(request.url || '');

      // Only handle paths starting with /ws
      if (pathname.startsWith('/ws')) {
        this.wss.handleUpgrade(request, socket, head, (ws) => {
          this.wss.emit('connection', ws, request);
        });
      }
    });

    // Handle new connections
    this.wss.on('connection', (ws: ExtendedWebSocket, request: IncomingMessage) => {
      this.handleConnection(ws, request);
    });

    // Start 30-second ping heartbeat
    this.startHeartbeat();
  }

  private getPathname(rawUrl: string): string {
    try {
      const url = new URL(rawUrl, 'http://localhost');
      return url.pathname;
    } catch {
      return rawUrl.split('?')[0] || '';
    }
  }

  private handleConnection(ws: ExtendedWebSocket, request: IncomingMessage): void {
    const rawUrl = request.url || '';
    const pathname = this.getPathname(rawUrl);
    ws.isAlive = true;
    ws.channels = new Set();
    ws.clientIp = request.socket.remoteAddress;

    ws.on('pong', () => {
      ws.isAlive = true;
    });

    // Check if this connection is an inbound publisher (Python worker publishing to Node)
    if (pathname.startsWith('/ws/publish')) {
      this.setupPublisher(ws, pathname, rawUrl);
      return;
    }

    // Otherwise, standard subscriber connection
    this.setupSubscriber(ws, pathname, rawUrl);
  }

  private setupSubscriber(ws: ExtendedWebSocket, pathname: string, rawUrl: string): void {
    ws.role = 'subscriber';
    const cleanPath = pathname.replace(/\/+$/, ''); // Remove trailing slashes

    // Route path to channels:
    // 1. /ws/feed/gate or /ws/feed/GATE-01
    // 2. /ws/feed/area or /ws/feed/BAI-KIEM
    // 3. /ws/feed/:cameraId
    // 4. /ws/events/gate
    // 5. /ws/events/area
    // 6. /ws/alerts
    let subscribedChannel: string | null = null;

    if (cleanPath === '/ws/feed/gate' || cleanPath === '/ws/feed/GATE-01') {
      subscribedChannel = 'feed:GATE-01';
    } else if (cleanPath === '/ws/feed/area' || cleanPath === '/ws/feed/BAI-KIEM') {
      subscribedChannel = 'feed:BAI-KIEM';
    } else if (cleanPath.startsWith('/ws/feed/')) {
      const camId = cleanPath.slice('/ws/feed/'.length);
      subscribedChannel = `feed:${channelManager.canonicalCameraId(camId)}`;
    } else if (cleanPath === '/ws/events/gate') {
      subscribedChannel = 'events:gate';
    } else if (cleanPath === '/ws/events/area') {
      subscribedChannel = 'events:area';
    } else if (cleanPath === '/ws/alerts') {
      subscribedChannel = 'alerts';
    } else {
      // Check query param e.g. /ws?channel=feed:GATE-01 or /ws/events?type=gate
      try {
        const url = new URL(rawUrl, 'http://localhost');
        const qChannel = url.searchParams.get('channel') || url.searchParams.get('stream');
        if (qChannel) {
          subscribedChannel = channelManager.canonicalChannelName(qChannel);
        }
      } catch {
        // ignore
      }
    }

    if (subscribedChannel) {
      channelManager.subscribe(subscribedChannel, ws);
      console.log(`[WS Server] Client (${ws.clientIp}) subscribed to ${subscribedChannel}`);

      // Send initial welcome/status message
      const welcome: WsMessage = {
        type: 'status',
        cameraId: subscribedChannel.startsWith('feed:') ? subscribedChannel.slice(5) : 'SYSTEM',
        status: 'ONLINE',
        timestamp: new Date().toISOString(),
        message: `Subscribed to ${subscribedChannel}`,
      };
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(welcome));
      }
    } else {
      console.log(`[WS Server] Client (${ws.clientIp}) connected to general path ${cleanPath}`);
    }

    // Handle inbound client messages (e.g. dynamic subscription requests or client pings)
    ws.on('message', (data: RawData) => {
      try {
        const str = data.toString('utf8');
        const msg = JSON.parse(str);
        if (msg.action === 'subscribe' && msg.channel) {
          const ch = channelManager.canonicalChannelName(msg.channel);
          channelManager.subscribe(ch, ws);
          ws.send(JSON.stringify({ status: 'subscribed', channel: ch }));
        } else if (msg.action === 'unsubscribe' && msg.channel) {
          const ch = channelManager.canonicalChannelName(msg.channel);
          channelManager.unsubscribe(ch, ws);
          ws.send(JSON.stringify({ status: 'unsubscribed', channel: ch }));
        } else if (msg.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', timestamp: Date.now() }));
        }
      } catch {
        // Non-JSON message from client, ignore
      }
    });

    ws.on('close', () => {
      channelManager.unsubscribeAll(ws);
    });

    ws.on('error', (err) => {
      console.error(`[WS Server] Subscriber error (${ws.clientIp}):`, err);
      channelManager.unsubscribeAll(ws);
    });
  }

  private setupPublisher(ws: ExtendedWebSocket, pathname: string, _rawUrl: string): void {
    ws.role = 'publisher';
    const cleanPath = pathname.replace(/\/+$/, '');
    console.log(`[WS Server] Inbound Publisher connected on ${cleanPath} (${ws.clientIp})`);

    // Inbound publisher sends messages which get broadcast to corresponding channels
    ws.on('message', (data: RawData) => {
      try {
        let msg: WsMessage;
        if (typeof data === 'string') {
          msg = JSON.parse(data);
        } else if (Buffer.isBuffer(data)) {
          // Check if JSON buffer
          try {
            msg = JSON.parse(data.toString('utf8'));
          } catch {
            // Raw binary frame: if publisher connected to /ws/publish/feed/:cameraId
            if (cleanPath.startsWith('/ws/publish/feed/')) {
              const camId = cleanPath.slice('/ws/publish/feed/'.length);
              channelManager.broadcastFeed(camId, data);
            }
            return;
          }
        } else {
          return;
        }

        // Broadcast based on message envelope or endpoint
        if (cleanPath.startsWith('/ws/publish/feed/')) {
          const camId = cleanPath.slice('/ws/publish/feed/'.length);
          channelManager.broadcastFeed(camId, msg as any);
        } else if (cleanPath === '/ws/publish/events/gate') {
          channelManager.broadcastGateEvent(msg);
        } else if (cleanPath === '/ws/publish/events/area') {
          channelManager.broadcastAreaEvent(msg);
        } else if (cleanPath === '/ws/publish/alerts') {
          channelManager.broadcastAlert(msg);
        } else {
          // General publisher: dispatch by message type
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
        }
      } catch (err) {
        console.error('[WS Server] Error processing publisher message:', err);
      }
    });

    ws.on('close', () => {
      console.log(`[WS Server] Publisher disconnected (${ws.clientIp})`);
    });

    ws.on('error', (err) => {
      console.error(`[WS Server] Publisher error (${ws.clientIp}):`, err);
    });
  }

  private startHeartbeat(): void {
    this.pingInterval = setInterval(() => {
      for (const client of this.wss.clients) {
        const extWs = client as ExtendedWebSocket;
        if (extWs.isAlive === false) {
          console.log(`[WS Server] Terminating inactive client (${extWs.clientIp})`);
          channelManager.unsubscribeAll(extWs);
          extWs.terminate();
          continue;
        }
        extWs.isAlive = false;
        extWs.ping();
      }
    }, 30000);
  }

  public close(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
    this.wss.close();
  }
}
