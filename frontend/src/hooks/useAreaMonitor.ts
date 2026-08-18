/**
 * hooks/useAreaMonitor.ts — Orchestration Hook for Area Monitoring Screen (VS-AREA-VIOLATION)
 *
 * Coordinates:
 * 1. REST initial violation loading (GET /api/v1/events/area)
 * 2. Real-time video frame + zone overlays via useCameraFeed('/ws/feed/area')
 * 3. Real-time violation events via useWebSocket('/ws/events/area')
 * 4. Merged presentation view model (violations + ephemeral allowed detections)
 * 5. Search, tab filters (all, violation, ok), and hover synchronization
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { getAreaEvents, getClipUrl } from '../api/events';
import type {
  AreaAction,
  AreaEvent,
  AreaViolationDto,
  PolygonZone,
} from '../types';
import { useCameraFeed } from './useCameraFeed';
import { useWebSocket } from './useWebSocket';

export interface AreaEventWsPacket extends AreaViolationDto {
  type: 'zone_violation';
  action?: AreaAction;
}

export const ZONE_COLOR_PALETTE = [
  '#3b82f6', // blue
  '#06b6d4', // cyan
  '#a855f7', // purple
  '#10b981', // green
  '#f59e0b', // amber
  '#f43f5e', // rose
];

export function getDeterministicZoneColor(zoneId: string): string {
  let hash = 0;
  for (let i = 0; i < zoneId.length; i++) {
    hash = (hash << 5) - hash + zoneId.charCodeAt(i);
    hash |= 0;
  }
  const index = Math.abs(hash) % ZONE_COLOR_PALETTE.length;
  return ZONE_COLOR_PALETTE[index];
}

function formatTimeString(isoOrDate: string | Date | number): string {
  const date = new Date(isoOrDate);
  if (Number.isNaN(date.getTime())) return '00:00:00';

  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function useAreaMonitor() {
  const [violations, setViolations] = useState<AreaEvent[]>([]);
  const [isLoadingRest, setIsLoadingRest] = useState<boolean>(true);
  const [restError, setRestError] = useState<string | null>(null);

  const [filterMode, setFilterMode] = useState<'all' | 'violation' | 'ok'>('all');
  const [searchFilter, setSearchFilter] = useState<string>('');
  const [hoveredEventId, setHoveredEventId] = useState<string | null>(null);
  const [hoveredTrackId, setHoveredTrackId] = useState<number | null>(null);
  const [hoveredZoneId, setHoveredZoneId] = useState<string | null>(null);

  // 1. Live video stream & detection/zone overlays
  const {
    frameImage,
    detections,
    zones: feedZones,
    fps,
    isOnline,
    statusText,
    lastTimestamp,
    reconnect: reconnectFeed,
  } = useCameraFeed('BAI-KIEM');

  // 2. Fetch initial violations page
  const fetchViolations = useCallback(async () => {
    try {
      setIsLoadingRest(true);
      setRestError(null);
      const res = await getAreaEvents({ limit: 50, offset: 0 });
      const mapped: AreaEvent[] = res.items.map((dto) => ({
        id: dto.id,
        time: formatTimeString(dto.enteredAt),
        obj: dto.objectLabel,
        zone: dto.zoneName,
        zoneId: dto.zoneId,
        st: 'Vi phạm',
        ok: false,
        source: 'violation',
        clipUrl: dto.clipUrl ? getClipUrl(dto.clipUrl) : null,
        durationSeconds: dto.durationSeconds,
      }));
      setViolations(mapped);
    } catch (err: any) {
      console.error('[useAreaMonitor] Failed to fetch area violations:', err);
      setRestError('Không thể tải lịch sử vi phạm. Nhấn để thử lại.');
    } finally {
      setIsLoadingRest(false);
    }
  }, []);

  useEffect(() => {
    fetchViolations();
  }, [fetchViolations]);

  // 3. Listen to real-time violation events on /ws/events/area
  const handleAreaEventMessage = useCallback((msg: AreaEventWsPacket) => {
    if (!msg || msg.type !== 'zone_violation') return;

    if (msg.action === 'STARTED' || msg.status === 'OPEN') {
      const newEvent: AreaEvent = {
        id: msg.id,
        time: formatTimeString(msg.enteredAt),
        obj: msg.objectLabel,
        zone: msg.zoneName || 'Khu vực giám sát',
        zoneId: msg.zoneId,
        st: 'Vi phạm',
        ok: false,
        source: 'violation',
        clipUrl: msg.clipUrl ? getClipUrl(msg.clipUrl) : null,
        durationSeconds: msg.durationSeconds,
      };

      setViolations((prev) => {
        const exists = prev.some((e) => e.id === msg.id);
        if (exists) return prev;
        return [newEvent, ...prev].slice(0, 50);
      });
    } else if (msg.action === 'ENDED' || msg.status === 'CLOSED') {
      setViolations((prev) =>
        prev.map((e) =>
          e.id === msg.id
            ? {
                ...e,
                durationSeconds: msg.durationSeconds,
                clipUrl: msg.clipUrl ? getClipUrl(msg.clipUrl) : e.clipUrl,
              }
            : e
        )
      );
    }
  }, []);

  useWebSocket<AreaEventWsPacket>({
    path: '/ws/events/area',
    onMessage: handleAreaEventMessage,
  });

  // 4. Derive live allowed events from current frame detections
  const liveAllowedEvents = useMemo<AreaEvent[]>(() => {
    const rows: AreaEvent[] = [];
    const nowStr = lastTimestamp ? formatTimeString(lastTimestamp) : formatTimeString(new Date());

    for (const det of detections) {
      if (det.status === 'ALLOWED' && typeof det.trackId === 'number' && det.zoneMatches && det.zoneMatches.length > 0) {
        for (const match of det.zoneMatches) {
          if (match.status === 'ALLOWED') {
            rows.push({
              id: `live:${det.trackId}:${match.zoneId}`,
              time: nowStr,
              obj: det.label || det.class,
              zone: match.zoneName,
              zoneId: match.zoneId,
              trackId: det.trackId,
              st: 'Được phép',
              ok: true,
              source: 'live_allowed',
            });
          }
        }
      }
    }
    return rows;
  }, [detections, lastTimestamp]);

  // 5. Merged Presentation List
  const allEvents = useMemo<AreaEvent[]>(() => {
    return [...violations, ...liveAllowedEvents];
  }, [violations, liveAllowedEvents]);

  // 6. Filtered Events
  const filteredEvents = useMemo<AreaEvent[]>(() => {
    return allEvents.filter((e) => {
      if (filterMode === 'violation' && e.ok) return false;
      if (filterMode === 'ok' && !e.ok) return false;

      if (searchFilter.trim()) {
        const q = searchFilter.toLowerCase().trim();
        return (
          e.obj.toLowerCase().includes(q) ||
          e.zone.toLowerCase().includes(q) ||
          e.time.toLowerCase().includes(q) ||
          e.st.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [allEvents, filterMode, searchFilter]);

  // 7. Formatted zones with theme colors
  const activeZones = useMemo<PolygonZone[]>(() => {
    if (feedZones && feedZones.length > 0) {
      return feedZones.map((fz) => {
        let pts: [number, number][] = [];
        if (Array.isArray(fz.polygon)) {
          pts = fz.polygon.map((p: any) => {
            if (typeof p === 'object' && p !== null && 'x' in p && 'y' in p) {
              return [p.x * 100, p.y * 100];
            }
            if (Array.isArray(p) && p.length >= 2) {
              return [p[0] * 100, p[1] * 100];
            }
            return [0, 0];
          });
        }
        const typesMap: Record<string, number> = {};
        if (Array.isArray(fz.targetLabels)) {
          fz.targetLabels.forEach((lbl) => {
            typesMap[lbl] = fz.ruleType === 'ALLOW_SPECIFIED' ? 1 : 0;
          });
        }

        return {
          id: fz.id,
          name: fz.name,
          color: getDeterministicZoneColor(fz.id),
          points: pts,
          types: typesMap,
          ruleType: fz.ruleType === 'ALLOW_SPECIFIED' ? 'ALLOW_SPECIFIED' : 'PROHIBIT_SPECIFIED',
          targetLabels: Array.isArray(fz.targetLabels) ? fz.targetLabels : [],
        };
      });
    }
    return [];
  }, [feedZones]);

  // 8. KPIs calculation
  const violationCount = violations.filter((v) => !v.ok).length;
  const objectsInZoneCount = detections.filter(
    (d) => d.zoneMatches && d.zoneMatches.length > 0
  ).length;
  const allowedInZoneCount = detections.filter(
    (d) => d.status === 'ALLOWED' && d.zoneMatches && d.zoneMatches.length > 0
  ).length;

  return {
    // Feed & Connection
    frameImage,
    detections,
    activeZones,
    fps,
    isOnline,
    statusText,
    reconnectFeed,
    // REST & Events
    violations,
    liveAllowedEvents,
    allEvents,
    filteredEvents,
    isLoadingRest,
    restError,
    fetchViolations,
    // Filters & UI State
    filterMode,
    setFilterMode,
    searchFilter,
    setSearchFilter,
    hoveredEventId,
    setHoveredEventId,
    hoveredTrackId,
    setHoveredTrackId,
    hoveredZoneId,
    setHoveredZoneId,
    // KPI metrics
    kpis: {
      objectsInZoneCount,
      violationCount,
      allowedInZoneCount,
      activeZonesCount: activeZones.length,
    },
  };
}
