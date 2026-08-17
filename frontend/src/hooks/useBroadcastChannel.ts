/**
 * hooks/useBroadcastChannel.ts — Cross-Tab Synchronization Hook (BR-08)
 *
 * Uses the native browser BroadcastChannel API to synchronize floating alerts
 * and live notifications across multiple open tabs without server roundtrips.
 */
import { useEffect, useRef, useCallback } from 'react';

export interface UseBroadcastChannelReturn<T> {
  postMessage: (message: T) => void;
  isSupported: boolean;
}

export function useBroadcastChannel<T = unknown>(
  channelName = 'sentriai-alerts',
  onMessage?: (data: T) => void
): UseBroadcastChannelReturn<T> {
  const channelRef = useRef<BroadcastChannel | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const isSupported = typeof window !== 'undefined' && 'BroadcastChannel' in window;

  useEffect(() => {
    if (!isSupported) {
      return;
    }

    try {
      const channel = new BroadcastChannel(channelName);
      channelRef.current = channel;

      channel.onmessage = (event: MessageEvent<T>) => {
        onMessageRef.current?.(event.data);
      };

      return () => {
        channel.close();
        channelRef.current = null;
      };
    } catch {
      // ignore
    }
  }, [channelName, isSupported]);

  const postMessage = useCallback(
    (message: T) => {
      if (channelRef.current) {
        try {
          channelRef.current.postMessage(message);
        } catch {
          // ignore
        }
      }
    },
    []
  );

  return {
    postMessage,
    isSupported,
  };
}
