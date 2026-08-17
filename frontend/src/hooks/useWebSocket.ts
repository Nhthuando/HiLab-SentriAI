/**
 * hooks/useWebSocket.ts — Generic React WebSocket Hook with Auto-Reconnect
 */
import { useEffect, useRef, useState, useCallback } from 'react';

export type ConnectionStatus = 'CONNECTING' | 'OPEN' | 'CLOSING' | 'CLOSED';

export interface UseWebSocketOptions<T = unknown> {
  url?: string;
  path?: string;
  autoConnect?: boolean;
  autoReconnect?: boolean;
  reconnectIntervalMs?: number;
  maxReconnectIntervalMs?: number;
  onOpen?: (event: Event) => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
  onMessage?: (data: T) => void;
}

export interface UseWebSocketReturn<T = unknown> {
  isConnected: boolean;
  status: ConnectionStatus;
  lastMessage: T | null;
  sendMessage: (data: unknown) => boolean;
  reconnect: () => void;
  disconnect: () => void;
}

export function useWebSocket<T = unknown>(
  options: UseWebSocketOptions<T> = {}
): UseWebSocketReturn<T> {
  const {
    url,
    path,
    autoConnect = true,
    autoReconnect = true,
    reconnectIntervalMs = 1500,
    maxReconnectIntervalMs = 10000,
    onOpen,
    onClose,
    onError,
    onMessage,
  } = options;

  const [status, setStatus] = useState<ConnectionStatus>('CLOSED');
  const [lastMessage, setLastMessage] = useState<T | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const currentBackoffRef = useRef<number>(reconnectIntervalMs);
  const isManuallyClosedRef = useRef<boolean>(false);

  const callbacksRef = useRef({ onOpen, onClose, onError, onMessage });
  callbacksRef.current = { onOpen, onClose, onError, onMessage };

  const getFullUrl = useCallback((): string => {
    if (url) return url;
    const baseWsUrl =
      (import.meta.env.VITE_WS_URL as string | undefined) || 'ws://localhost:3001';
    const cleanPath = path ? (path.startsWith('/') ? path : `/${path}`) : '';
    return `${baseWsUrl}${cleanPath}`;
  }, [url, path]);

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    if (reconnectTimeoutRef.current) {
      window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    const targetUrl = getFullUrl();
    setStatus('CONNECTING');
    isManuallyClosedRef.current = false;

    try {
      const ws = new WebSocket(targetUrl);
      socketRef.current = ws;

      ws.onopen = (event) => {
        setStatus('OPEN');
        currentBackoffRef.current = reconnectIntervalMs;
        callbacksRef.current.onOpen?.(event);
      };

      ws.onclose = (event) => {
        setStatus('CLOSED');
        callbacksRef.current.onClose?.(event);

        if (!isManuallyClosedRef.current && autoReconnect) {
          reconnectTimeoutRef.current = window.setTimeout(() => {
            currentBackoffRef.current = Math.min(
              currentBackoffRef.current * 1.5,
              maxReconnectIntervalMs
            );
            connect();
          }, currentBackoffRef.current);
        }
      };

      ws.onerror = (event) => {
        callbacksRef.current.onError?.(event);
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const parsed = JSON.parse(event.data) as T;
          setLastMessage(parsed);
          callbacksRef.current.onMessage?.(parsed);
        } catch {
          // If raw text or non-JSON
          setLastMessage(event.data as T);
          callbacksRef.current.onMessage?.(event.data as T);
        }
      };
    } catch {
      setStatus('CLOSED');
    }
  }, [getFullUrl, autoReconnect, reconnectIntervalMs, maxReconnectIntervalMs]);

  const disconnect = useCallback(() => {
    isManuallyClosedRef.current = true;
    if (reconnectTimeoutRef.current) {
      window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
    setStatus('CLOSED');
  }, []);

  const sendMessage = useCallback((data: unknown): boolean => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      const payload = typeof data === 'string' ? data : JSON.stringify(data);
      socketRef.current.send(payload);
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    if (autoConnect) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    isConnected: status === 'OPEN',
    status,
    lastMessage,
    sendMessage,
    reconnect: connect,
    disconnect,
  };
}
