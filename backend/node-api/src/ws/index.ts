/**
 * index.ts — Main Entry Point for SentriAI WebSocket Proxy Subsystem
 */
import type { Server as HttpServer } from 'http';
import { channelManager, ChannelManager } from './channels';
import { pythonConnector, PythonWorkerConnector } from './pythonConnector';
import { SentriWebSocketServer } from './server';
import type {
  AlertMessage,
  AreaEventMessage,
  CameraId,
  DetectionBox,
  FrameMessage,
  GateEventMessage,
  StatusMessage,
  WsMessage,
} from './types';

let _wsServerInstance: SentriWebSocketServer | null = null;

/**
 * Initialize and attach WebSocket Proxy to the HTTP server.
 * Also starts the PythonWorkerConnector to listen for stream events.
 */
export function setupWebSocketProxy(httpServer: HttpServer): {
  wsServer: SentriWebSocketServer;
  channelManager: ChannelManager;
  pythonConnector: PythonWorkerConnector;
} {
  if (!_wsServerInstance) {
    console.log('[WS Proxy] Initializing SentriAI WebSocket Proxy subsystem...');
    _wsServerInstance = new SentriWebSocketServer(httpServer);

    // Start background outbound connection to Python Worker (fails gracefully if worker not running)
    pythonConnector.start();
  }

  return {
    wsServer: _wsServerInstance,
    channelManager,
    pythonConnector,
  };
}

export {
  channelManager,
  ChannelManager,
  pythonConnector,
  PythonWorkerConnector,
  SentriWebSocketServer,
};

export type {
  AlertMessage,
  AreaEventMessage,
  CameraId,
  DetectionBox,
  FrameMessage,
  GateEventMessage,
  StatusMessage,
  WsMessage,
};
