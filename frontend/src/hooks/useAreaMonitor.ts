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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getAreaEvents, getClipUrl } from '../api/events';
import type {
  AreaAction,
  AreaEvent,
  AreaViolationDto,
  PolygonZone,
} from '../types';
import { useCameraFeed, type BoundingBoxDetection } from './useCameraFeed';
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

const DETECTION_PRESENTATION_GRACE_MS = 12_000;

interface StableDetectionEntry {
  actualTrackId: number;
  presentationTrackId: number;
  detection: BoundingBoxDetection;
  lastSeenAt: number;
}

function hasZoneMatch(detection: BoundingBoxDetection): boolean {
  return Boolean(detection.zoneMatches?.length);
}

function sharesZone(first: BoundingBoxDetection, second: BoundingBoxDetection): boolean {
  const firstZoneIds = new Set((first.zoneMatches || []).map((match) => match.zoneId));
  return (second.zoneMatches || []).some((match) => firstZoneIds.has(match.zoneId));
}

function detectionBoxesAreContinuous(
  first: BoundingBoxDetection,
  second: BoundingBoxDetection,
): boolean {
  const firstBox = first.normalized_bbox || first.bbox;
  const secondBox = second.normalized_bbox || second.bbox;
  if (!firstBox || !secondBox) return false;

  const firstCenterX = (firstBox[0] + firstBox[2]) / 2;
  const firstCenterY = (firstBox[1] + firstBox[3]) / 2;
  const secondCenterX = (secondBox[0] + secondBox[2]) / 2;
  const secondCenterY = (secondBox[1] + secondBox[3]) / 2;

  const firstWidth = Math.max(0.0001, firstBox[2] - firstBox[0]);
  const firstHeight = Math.max(0.0001, firstBox[3] - firstBox[1]);
  const secondWidth = Math.max(0.0001, secondBox[2] - secondBox[0]);
  const secondHeight = Math.max(0.0001, secondBox[3] - secondBox[1]);
  const left = Math.max(firstBox[0], secondBox[0]);
  const top = Math.max(firstBox[1], secondBox[1]);
  const right = Math.min(firstBox[2], secondBox[2]);
  const bottom = Math.min(firstBox[3], secondBox[3]);
  const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
  const union = firstWidth * firstHeight + secondWidth * secondHeight - intersection;
  const iou = union > 0 ? intersection / union : 0;
  const centerDistance = Math.hypot(firstCenterX - secondCenterX, firstCenterY - secondCenterY);

  return iou >= 0.2 || centerDistance <= 0.12;
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
    sourceResetSequence,
    reconnect: reconnectFeed,
  } = useCameraFeed('BAI-KIEM');

  // The detector can skip several frames or receive a new ByteTrack ID for
  // the same object. Keep an Area-only presentation identity for a short
  // window so live allowed rows and overlay boxes do not flash or jump.
  const stableDetectionEntriesRef = useRef<Map<number, StableDetectionEntry>>(new Map());
  const processedSourceResetSequenceRef = useRef(0);
  const [stableDetections, setStableDetections] = useState<BoundingBoxDetection[]>([]);

  useEffect(() => {
    const observedAt = lastTimestamp ?? Date.now();
    const observedTrackIds = new Set<number>();
    const currentInZone = detections.filter((detection) => {
      if (typeof detection.trackId === 'number') {
        observedTrackIds.add(detection.trackId);
      }
      return typeof detection.trackId === 'number' && hasZoneMatch(detection);
    });
    const entries = stableDetectionEntriesRef.current;
    if (processedSourceResetSequenceRef.current !== sourceResetSequence) {
      entries.clear();
      processedSourceResetSequenceRef.current = sourceResetSequence;
    }
    const refreshedPresentationIds = new Set<number>();

    for (const detection of currentInZone) {
      const actualTrackId = detection.trackId as number;
      let entry = Array.from(entries.values()).find(
        (candidate) => candidate.actualTrackId === actualTrackId,
      );

      if (!entry) {
        entry = Array.from(entries.values()).find(
          (candidate) =>
            !refreshedPresentationIds.has(candidate.presentationTrackId) &&
            !observedTrackIds.has(candidate.actualTrackId) &&
            observedAt - candidate.lastSeenAt <= DETECTION_PRESENTATION_GRACE_MS &&
            candidate.detection.class === detection.class &&
            sharesZone(candidate.detection, detection) &&
            detectionBoxesAreContinuous(candidate.detection, detection),
        );
      }

      if (!entry) {
        entry = {
          actualTrackId,
          presentationTrackId: actualTrackId,
          detection,
          lastSeenAt: observedAt,
        };
        entries.set(entry.presentationTrackId, entry);
      }

      const stableEntry = entry;
      if (!stableEntry) continue;

      stableEntry.actualTrackId = actualTrackId;
      stableEntry.detection = { ...detection, trackId: stableEntry.presentationTrackId };
      stableEntry.lastSeenAt = observedAt;
      refreshedPresentationIds.add(stableEntry.presentationTrackId);
    }

    for (const [presentationTrackId, entry] of entries) {
      if (refreshedPresentationIds.has(presentationTrackId)) continue;
      // The same confirmed track is still visible but no longer intersects a
      // zone: remove it immediately. Only entirely missing tracks get grace.
      if (
        observedTrackIds.has(entry.actualTrackId) ||
        observedAt - entry.lastSeenAt > DETECTION_PRESENTATION_GRACE_MS
      ) {
        entries.delete(presentationTrackId);
      }
    }

    setStableDetections(
      Array.from(entries.values())
        .sort((first, second) => first.presentationTrackId - second.presentationTrackId)
        .map((entry) => entry.detection),
    );
  }, [detections, lastTimestamp, sourceResetSequence]);

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

    for (const det of stableDetections) {
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
  }, [stableDetections, lastTimestamp]);

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
  const objectsInZoneCount = stableDetections.filter(
    (d) => d.zoneMatches && d.zoneMatches.length > 0
  ).length;
  const allowedInZoneCount = stableDetections.filter(
    (d) => d.status === 'ALLOWED' && d.zoneMatches && d.zoneMatches.length > 0
  ).length;

  return {
    // Feed & Connection
    frameImage,
    detections: stableDetections,
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
