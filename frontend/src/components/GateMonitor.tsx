import React, { useState, useMemo, useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { GateEvent, PolygonZone } from '../types';
import { useCameraFeed } from '../hooks/useCameraFeed';
import { useWebSocket } from '../hooks/useWebSocket';
import { deleteGateEvents, getCropImageUrl, getGateEvents } from '../api/events';
import { getCameraPlayback, seekCamera } from '../api/zones';

interface GateMonitorProps {
  zones: PolygonZone[];
  events: GateEvent[];
  labels: Record<string, 'quen' | 'la'>;
}

function normalizeGateEvent(raw: any): GateEvent | null {
  if (!raw || typeof raw !== 'object') return null;
  const rawPlate = raw.plate || raw.licensePlate;
  const isUnknown = rawPlate === 'UNKNOWN' || raw.status === 'unknown';
  const plate = isUnknown ? 'Không xác định' : rawPlate;
  if (!plate || plate === '—' || plate === 'â€”') return null;
  const rawStatus = raw.status;
  const status: 'quen' | 'la' | 'unknown' = isUnknown
    ? 'unknown'
    : rawStatus === 'KNOWN' || rawStatus === 'quen' ? 'quen' : 'la';
  const confidence = isUnknown
    ? null
    : typeof raw.conf === 'number'
      ? raw.conf
      : typeof raw.confidence === 'number'
        ? Math.round(raw.confidence * 100)
        : null;

  return {
    id: raw.id || `${plate}-${raw.time || Date.now()}`,
    time: raw.videoTimecode || raw.time || '00:00',
    plate,
    zone: raw.zoneName || raw.zone || (raw.lane === 'IN_2' ? 'Làn IN 2 · Làn phụ' : 'Làn IN 1 · Cổng chính'),
    conf: confidence,
    status,
    clipPath: raw.clipPath ?? null,
    cropPath: raw.cropPath ?? null,
    cameraId: raw.cameraId,
    lane: raw.lane,
    eventTimestamp: raw.eventTimestamp,
    eventKey: raw.eventKey ?? null,
  };
}

function mergeGateEvent(prev: GateEvent[], next: GateEvent): GateEvent[] {
  const key = next.eventKey || next.id;
  const existingIndex = prev.findIndex((event) => (event.eventKey || event.id) === key);
  if (existingIndex === -1) return [next, ...prev].slice(0, 50);

  const existing = prev[existingIndex];
  const nextConf = next.conf ?? -1;
  const existingConf = existing.conf ?? -1;
  if (nextConf < existingConf) return prev;

  const merged = [...prev];
  merged[existingIndex] = { ...existing, ...next, id: existing.id || next.id };
  return merged;
}

export const GateMonitor: React.FC<GateMonitorProps> = ({ zones, events: initialEvents, labels }) => {
  const [liveEvents, setLiveEvents] = useState<GateEvent[]>(initialEvents);
  const [hoveredEventId, setHoveredEventId] = useState<string | null>(null);
  const [hoveredPlate, setHoveredPlate] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<'all' | 'la' | 'quen'>('all');
  const [searchFilter, setSearchFilter] = useState<string>('');
  const [isClearing, setIsClearing] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const handleClearGateEvents = async () => {
    if (liveEvents.length === 0) return;
    const ok = window.confirm('Bạn có chắc chắn muốn xóa toàn bộ nhật ký biển số và các hình ảnh/video clip liên quan?');
    if (!ok) return;

    setIsClearing(true);
    try {
      await deleteGateEvents();
      setLiveEvents([]);
      setToastMessage('Đã xóa toàn bộ nhật ký biển số thành công');
      window.setTimeout(() => setToastMessage(null), 3000);
    } catch (err) {
      console.error('Failed to clear gate events:', err);
    } finally {
      setIsClearing(false);
    }
  };
  const [playback, setPlayback] = useState({ seekable: false, positionMs: 0, durationMs: 0 });
  const [isSeeking, setIsSeeking] = useState(false);
  const [selectedCrop, setSelectedCrop] = useState<{ plate: string; url: string } | null>(null);

  // 1. Live Video Feed from WebSocket proxy (/ws/feed/gate)
  const {
    frameImage,
    detections,
    fps,
    isOnline,
    statusText,
    timecode,
    frameWidth,
    frameHeight,
    reconnect: reconnectFeed,
  } = useCameraFeed('GATE-01');
  const [isPaused, setIsPaused] = useState(false);
  const [frozenFrame, setFrozenFrame] = useState<string | null>(null);
  const [frozenDetections, setFrozenDetections] = useState<typeof detections>([]);

  const displayFrame = isPaused ? (frozenFrame || frameImage) : frameImage;
  const displayDetections = isPaused ? frozenDetections : detections;

  const togglePause = () => {
    if (isPaused) {
      setIsPaused(false);
      return;
    }
    setFrozenFrame(frameImage);
    setFrozenDetections(detections);
    setIsPaused(true);
  };

  // 2. Initial load of Gate Events from REST API (AP-02)
  useEffect(() => {
    getGateEvents({ limit: 50 })
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setLiveEvents(data);
        }
      })
      .catch((err) => {
        console.warn('Failed to fetch initial gate events from API:', err);
      });
  }, []);

  useEffect(() => {
    let active = true;
    const refreshPlayback = () => {
      if (isSeeking) return;
      getCameraPlayback('GATE-01')
        .then((status) => {
          if (active) setPlayback(status);
        })
        .catch(() => {});
    };
    refreshPlayback();
    const timer = window.setInterval(refreshPlayback, 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [isSeeking]);

  const formatDuration = (ms: number) => {
    const total = Math.max(0, Math.floor(ms / 1000));
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };
  const displayedTimecode = playback.seekable
    ? formatDuration(playback.positionMs)
    : (/^\d{1,3}:\d{2}$/.test(timecode || '') ? timecode : '00:00');

  const handleSeekCommit = (value: number) => {
    const boundedValue = Math.max(0, Math.min(playback.durationMs || value, value));
    setIsSeeking(false);
    seekCamera('GATE-01', boundedValue)
      .then((status) => {
        setPlayback(status);
        setHoveredEventId(null);
        setHoveredPlate(null);
      })
      .catch(() => {});
  };

  const handleQuickSeek = (deltaMs: number) => {
    handleSeekCommit(playback.positionMs + deltaMs);
  };

  useEffect(() => {
    setLiveEvents((prev) => {
      const merged = new Map<string, GateEvent>();
      [...initialEvents, ...prev].forEach((event) => merged.set(event.id, event));
      return Array.from(merged.values()).slice(0, 50);
    });
  }, [initialEvents]);

  // 3. Real-time Event Push from WebSocket proxy (/ws/events/gate)
  useWebSocket<{ type: string; data: GateEvent }>({
    path: '/ws/events/gate',
    onMessage: (msg) => {
      if (isPaused) return;
      const newEv = normalizeGateEvent(msg?.data || msg);
      if (!newEv) return;
      setLiveEvents((prev) => mergeGateEvent(prev, newEv));
    },
  });

  const unreadCount = liveEvents.filter((e) => e.conf === null).length;
  const readCount = liveEvents.length - unreadCount;
  const readRate = liveEvents.length > 0 ? ((readCount / liveEvents.length) * 100).toFixed(0) : '100';

  const kpis = [
    {
      label: 'Lượt xe qua cổng',
      value: String(liveEvents.length),
      sub: 'Hôm nay',
      color: 'var(--ink)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--acc)" strokeWidth="2">
          <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.5 2.8C2.1 10.9 2 11.2 2 11.5V16c0 .6.4 1 1 1h2" />
          <circle cx="7" cy="17" r="2" />
          <path d="M9 17h6" />
          <circle cx="17" cy="17" r="2" />
        </svg>
      ),
    },
    {
      label: 'Biển số đọc thành công',
      value: String(readCount),
      sub: `${readRate}% tổng số lượt`,
      color: 'var(--ok)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      ),
    },
    {
      label: 'Không đọc được biển',
      value: String(unreadCount),
      sub: 'Cần kiểm tra thủ công',
      color: 'var(--p1)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--p1)" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      ),
    },
    {
      label: 'Độ tin cậy trung bình',
      value: '96.4%',
      sub: 'Mô hình AI LPR v2.4',
      color: 'var(--cyan)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" strokeWidth="2">
          <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        </svg>
      ),
    },
  ];

  // Filter events
  const filteredEvents = useMemo(() => {
    return liveEvents.filter((e) => {
      // 1. Status Filter
      if (filterMode === 'la') {
        if (e.status === 'unknown') return false;
        const isKnown = (labels[e.plate] || e.status) === 'quen';
        if (isKnown && e.plate !== '—') return false;
      } else if (filterMode === 'quen') {
        if (e.status === 'unknown') return false;
        const isKnown = (labels[e.plate] || e.status) === 'quen';
        if (!isKnown) return false;
      }

      // 2. Search
      if (searchFilter.trim()) {
        const q = searchFilter.toLowerCase().trim();
        return (
          e.plate.toLowerCase().includes(q) ||
          e.zone.toLowerCase().includes(q) ||
          e.time.includes(q)
        );
      }
      return true;
    });
  }, [liveEvents, labels, filterMode, searchFilter]);

  return (
    <div style={{ padding: '24px', maxWidth: '1420px', margin: '0 auto' }}>
      {/* 4 KPI Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: '16px',
          marginBottom: '24px',
        }}
      >
        {kpis.map((kpi, idx) => (
          <div
            key={idx}
            className="glass-panel"
            style={{
              padding: '16px 20px',
              borderRadius: '14px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              boxShadow: 'var(--shadow-sm)',
            }}
          >
            <div>
              <div style={{ fontSize: '12px', color: 'var(--ink2)', fontWeight: 600, marginBottom: '6px' }}>
                {kpi.label}
              </div>
              <div style={{ fontSize: '24px', fontWeight: 800, color: kpi.color, fontFamily: 'var(--font-mono)' }}>
                {kpi.value}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--ink3)', marginTop: '4px' }}>{kpi.sub}</div>
            </div>
            <div
              style={{
                width: '42px',
                height: '42px',
                borderRadius: '10px',
                backgroundColor: 'var(--raise)',
                border: '1px solid var(--line2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {kpi.icon}
            </div>
          </div>
        ))}
      </div>

      {/* Main 2-Column Layout: Video Feed & Sidebar */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1.4fr 1fr',
          gap: '20px',
          alignItems: 'start',
        }}
      >
        {/* Left: Feed & Controls */}
        <div>
          <div
            className="glass-panel"
            style={{
              borderRadius: '8px',
              padding: '8px 12px',
              marginBottom: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '10px',
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <span
                className={!isPaused && isOnline ? 'animate-live' : ''}
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  backgroundColor: isPaused ? 'var(--p1)' : (isOnline ? 'var(--p0)' : 'var(--ink3)'),
                  display: 'inline-block',
                }}
              />
              <span style={{ fontSize: '11.5px', fontWeight: 700, color: isPaused ? 'var(--p1)' : (isOnline ? 'var(--p0)' : 'var(--ink3)') }}>
                {isPaused ? 'TẠM DỪNG' : (isOnline ? 'TRỰC TIẾP' : 'NGOẠI TUYẾN')}
              </span>
              <span style={{ color: 'var(--line2)' }}>|</span>
              <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink)' }}>
                GATE-01 · Làn xe vào chính
              </span>
              <span style={{ fontSize: '10.5px', fontFamily: 'var(--font-mono)', color: 'var(--ink3)' }}>
                {frameWidth}x{frameHeight} · {isPaused ? 'TẠM DỪNG' : `${fps.toFixed(0)} FPS`}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <button
                type="button"
                onClick={togglePause}
                title={isPaused ? 'Tiếp tục phát video' : 'Tạm dừng video để kiểm tra'}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  border: isPaused ? '1px solid var(--p1)' : '1px solid var(--line2)',
                  backgroundColor: isPaused ? 'var(--p1q)' : 'var(--raise)',
                  color: isPaused ? 'var(--p1)' : 'var(--ink)',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                {isPaused ? (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3" /></svg>
                    <span>Tiếp tục</span>
                  </>
                ) : (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" /></svg>
                    <span>Tạm dừng</span>
                  </>
                )}
              </button>
              <span style={{ fontSize: '11.5px', fontFamily: 'var(--font-mono)', color: 'var(--ink)', fontWeight: 600 }}>
                {displayedTimecode}
              </span>
            </div>
          </div>

          {/* Feed Container */}
          <div
            style={{
              position: 'relative',
              width: '100%',
              aspectRatio: '16/9',
              backgroundColor: '#07090c',
              border: '1px solid var(--line2)',
              borderRadius: '16px',
              overflow: 'hidden',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            {/* Real WebSocket JPEG Frame or Static Fallback Image */}
            {displayFrame ? (
              <img
                src={displayFrame}
                alt="Live Camera Feed GATE-01"
                style={{
                  position: 'absolute',
                  inset: 0,
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                }}
              />
            ) : (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  backgroundImage: `url('/assets/cam-gate.png')`,
                  backgroundSize: 'cover',
                  backgroundPosition: 'center',
                }}
              />
            )}
            <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(5, 8, 12, 0.08)' }} />

            {/* Disconnected Overlay (AC-09) */}
            {!isOnline && (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  backgroundColor: 'rgba(7, 9, 12, 0.85)',
                  backdropFilter: 'blur(6px)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 30,
                  gap: '12px',
                }}
              >
                <div
                  style={{
                    width: '48px',
                    height: '48px',
                    borderRadius: '50%',
                    backgroundColor: 'var(--p0q)',
                    border: '2px solid var(--p0)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--p0)',
                  }}
                >
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="1" y1="1" x2="23" y2="23" />
                    <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
                    <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
                    <path d="M10.71 5.05A16 16 0 0 1 22.58 9" />
                    <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
                    <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
                    <line x1="12" y1="20" x2="12.01" y2="20" />
                  </svg>
                </div>
                <div style={{ fontSize: '15px', fontWeight: 700, color: '#ffffff' }}>{statusText}</div>
                <div style={{ fontSize: '12px', color: 'var(--ink2)', textAlign: 'center', maxWidth: '300px' }}>
                  Camera GATE-01 đang tự động kết nối lại...
                </div>
                <button
                  onClick={reconnectFeed}
                  style={{
                    marginTop: '6px',
                    padding: '7px 16px',
                    borderRadius: '8px',
                    backgroundColor: 'var(--acc)',
                    color: '#ffffff',
                    border: 'none',
                    fontSize: '12px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Thử kết nối lại
                </button>
              </div>
            )}

            {/* SVG Polygon Zones */}
            <svg
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
              }}
            >
              {zones.map((zone) => {
                const pointsStr = zone.points.map((p) => `${p[0]},${p[1]}`).join(' ');
                return (
                  <polygon
                    key={zone.id}
                    points={pointsStr}
                    fill={`${zone.color}16`}
                    stroke={zone.color}
                    strokeWidth="1.6"
                    strokeDasharray="6 4"
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
            </svg>

            {/* Zone Labels */}
            {zones.map((zone) => {
              const topPoint = zone.points.reduce((prev, curr) => (curr[1] < prev[1] ? curr : prev), zone.points[0]);
              return (
                <span
                  key={`label-${zone.id}`}
                  style={{
                    position: 'absolute',
                    left: `${topPoint[0]}%`,
                    top: `${topPoint[1]}%`,
                    transform: 'translateY(-115%)',
                    fontSize: '10px',
                    fontWeight: 700,
                    color: '#ffffff',
                    backgroundColor: `${zone.color}cc`,
                    padding: '2px 8px',
                    borderRadius: '4px',
                    backdropFilter: 'blur(4px)',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.5)',
                    pointerEvents: 'none',
                    letterSpacing: '0.04em',
                  }}
                >
                  {zone.name.toUpperCase()}
                </span>
              );
            })}

            {/* Dynamic Real-Time YOLO & Universal LPR Bounding Boxes */}
            {displayDetections.map((det, idx) => {
              const [x1, y1, x2, y2] = det.bbox;
              const isNorm = x2 <= 1.0 && y2 <= 1.0;
              const isPct = !isNorm && x2 <= 100.0 && y2 <= 100.0;
              const leftPct = isNorm ? x1 * 100 : isPct ? x1 : (x1 / frameWidth) * 100;
              const topPct = isNorm ? y1 * 100 : isPct ? y1 : (y1 / frameHeight) * 100;
              const widthPct = isNorm ? (x2 - x1) * 100 : isPct ? (x2 - x1) : ((x2 - x1) / frameWidth) * 100;
              const heightPct = isNorm ? (y2 - y1) * 100 : isPct ? (y2 - y1) : ((y2 - y1) / frameHeight) * 100;

              const plateText = (det as any).plate || '';
              const rawConf = Number((det as any).confidence ?? (det as any).conf ?? 0.95);
              const confPercent = Math.round(rawConf <= 1.0 ? rawConf * 100 : rawConf);
              const isStranger = labels[plateText] !== 'quen';
              const isBoxHovered = plateText && (hoveredPlate === plateText || hoveredEventId === plateText);

              return (
                <div
                  key={(det as any).track_id || `det-${idx}`}
                  onMouseEnter={() => plateText && setHoveredPlate(plateText)}
                  onMouseLeave={() => setHoveredPlate(null)}
                  style={{
                    position: 'absolute',
                    left: `${leftPct}%`,
                    top: `${topPct}%`,
                    width: `${widthPct}%`,
                    height: `${heightPct}%`,
                    border: `2px solid ${isBoxHovered ? '#ffffff' : (isStranger ? 'var(--p0)' : 'var(--cyan)')}`,
                    backgroundColor: isBoxHovered ? 'rgba(6, 182, 212, 0.35)' : 'rgba(6, 182, 212, 0.08)',
                    borderRadius: '6px',
                    boxShadow: isBoxHovered
                      ? '0 0 24px var(--cyan-glow), 0 0 10px #ffffff'
                      : '0 0 12px rgba(6, 182, 212, 0.4)',
                    transition: 'all 0.15s ease',
                    cursor: plateText ? 'pointer' : 'default',
                    zIndex: 15,
                  }}
                >
                  {plateText ? (
                    <div
                      style={{
                        position: 'absolute',
                        left: '50%',
                        top: '-26px',
                        transform: 'translateX(-50%)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        backgroundColor: isBoxHovered ? '#ffffff' : '#0e1726',
                        color: isBoxHovered ? '#000000' : '#ffffff',
                        border: `1.5px solid ${isStranger ? 'var(--p0)' : 'var(--cyan)'}`,
                        fontSize: '11px',
                        fontWeight: 700,
                        fontFamily: 'var(--font-mono)',
                        padding: '2px 8px',
                        borderRadius: '5px',
                        whiteSpace: 'nowrap',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
                      }}
                    >
                      <span>{plateText}</span>
                      <span
                        style={{
                          fontSize: '9.5px',
                          padding: '1px 5px',
                          borderRadius: '3px',
                          backgroundColor: 'rgba(255, 255, 255, 0.12)',
                          color: confPercent >= 85 ? 'var(--ok)' : 'var(--cyan)',
                          fontWeight: 700,
                        }}
                      >
                        {confPercent}%
                      </span>
                      <span
                        style={{
                          fontSize: '9px',
                          padding: '1px 4px',
                          borderRadius: '3px',
                          backgroundColor: isStranger ? 'var(--p0)' : 'var(--ok)',
                          color: '#ffffff',
                        }}
                      >
                        {isStranger ? 'Xe lạ' : 'Xe quen'}
                      </span>
                    </div>
                  ) : (
                    <div
                      style={{
                        position: 'absolute',
                        left: '50%',
                        top: '-24px',
                        transform: 'translateX(-50%)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '5px',
                        backgroundColor: 'rgba(14, 23, 38, 0.92)',
                        color: 'var(--cyan)',
                        border: '1px solid var(--cyan)',
                        fontSize: '10px',
                        fontWeight: 600,
                        padding: '1px 7px',
                        borderRadius: '4px',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'var(--cyan)' }} />
                      <span>Đang quét biển số...</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {playback.seekable && (
            <div
              className="glass-card"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                marginTop: '12px',
                padding: '10px 14px',
                borderRadius: '12px',
                backgroundColor: 'var(--panel)',
                border: '1px solid var(--line2)',
              }}
            >
              <button
                type="button"
                onClick={() => handleQuickSeek(-10_000)}
                title="Lùi 10 giây"
                style={{
                  padding: '4px 8px',
                  borderRadius: '6px',
                  border: '1px solid var(--line2)',
                  background: 'var(--raise)',
                  color: 'var(--ink2)',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                -10s
              </button>

              <button
                type="button"
                onClick={togglePause}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  padding: '5px 12px',
                  borderRadius: '6px',
                  border: isPaused ? '1px solid var(--p1)' : 'none',
                  background: isPaused ? 'var(--p1q)' : 'var(--acc)',
                  color: isPaused ? 'var(--p1)' : '#ffffff',
                  fontSize: '12px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {isPaused ? '▶ Tiếp tục' : '⏸ Tạm dừng'}
              </button>

              <button
                type="button"
                onClick={() => handleQuickSeek(10_000)}
                title="Tua 10 giây"
                style={{
                  padding: '4px 8px',
                  borderRadius: '6px',
                  border: '1px solid var(--line2)',
                  background: 'var(--raise)',
                  color: 'var(--ink2)',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                +10s
              </button>

              <span style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--ink2)', minWidth: '95px', fontWeight: 600, textAlign: 'center' }}>
                {formatDuration(playback.positionMs)} / {formatDuration(playback.durationMs)}
              </span>

              <input
                type="range"
                min={0}
                max={Math.max(1, playback.durationMs)}
                value={Math.min(playback.positionMs, Math.max(1, playback.durationMs))}
                onChange={(event) => {
                  setIsSeeking(true);
                  setPlayback((prev) => ({ ...prev, positionMs: Number(event.target.value) }));
                }}
                onMouseUp={(event) => handleSeekCommit(Number(event.currentTarget.value))}
                onTouchEnd={(event) => handleSeekCommit(Number(event.currentTarget.value))}
                style={{ flex: 1, accentColor: 'var(--acc)', cursor: 'pointer', height: '6px' }}
              />
            </div>
          )}

          {/* Feed Legend */}
          <div
            style={{
              display: 'flex',
              gap: '20px',
              marginTop: '14px',
              fontSize: '11.5px',
              color: 'var(--ink2)',
              flexWrap: 'wrap',
              padding: '0 4px',
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <span
                style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '3px',
                  border: '1.8px solid var(--cyan)',
                  backgroundColor: 'var(--cyanq)',
                }}
              />
              Khung biển số nhận diện (Hover để làm nổi bật)
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <span
                style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '3px',
                  border: '1.5px dashed var(--ok)',
                  backgroundColor: 'var(--okq)',
                }}
              />
              Zone làn vào (Đang giám sát)
            </span>
          </div>
        </div>

        {/* Right: Recognized Plates List with Filter & Search */}
        <div
          className="glass-panel"
          style={{
            borderRadius: '16px',
            overflow: 'hidden',
            boxShadow: 'var(--shadow-lg)',
            display: 'flex',
            flexDirection: 'column',
            maxHeight: '620px',
          }}
        >
          {/* Header */}
          <div
            style={{
              padding: '16px 20px',
              borderBottom: '1px solid var(--line)',
              backgroundColor: 'var(--panel)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--ink)' }}>
                Nhật ký biển số nhận diện
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span
                  style={{
                    fontSize: '11px',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--ink3)',
                    backgroundColor: 'var(--raise)',
                    padding: '3px 8px',
                    borderRadius: '6px',
                  }}
                >
                  {filteredEvents.length} lượt
                </span>

                {/* Clear All Gate Events Button */}
                <button
                  onClick={handleClearGateEvents}
                  disabled={isClearing || liveEvents.length === 0}
                  title="Xóa toàn bộ nhật ký biển số và giải phóng ảnh crop, video clip"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '11px',
                    fontWeight: 600,
                    padding: '3px 8px',
                    borderRadius: '6px',
                    border: '1px solid rgba(244, 63, 94, 0.3)',
                    backgroundColor: 'rgba(244, 63, 94, 0.1)',
                    color: 'var(--p0)',
                    cursor: isClearing || liveEvents.length === 0 ? 'not-allowed' : 'pointer',
                    opacity: liveEvents.length === 0 ? 0.5 : 1,
                    transition: 'all 0.15s ease',
                  }}
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    <line x1="10" y1="11" x2="10" y2="17" />
                    <line x1="14" y1="11" x2="14" y2="17" />
                  </svg>
                  <span>{isClearing ? 'Đang xóa...' : 'Xóa nhật ký'}</span>
                </button>
              </div>
            </div>

            {/* Filter Tabs & Search */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div
                style={{
                  display: 'flex',
                  backgroundColor: 'var(--bg)',
                  border: '1px solid var(--line2)',
                  borderRadius: '8px',
                  padding: '3px',
                  gap: '2px',
                }}
              >
                <button
                  onClick={() => setFilterMode('all')}
                  style={{
                    flex: 1,
                    fontSize: '11.5px',
                    fontWeight: 600,
                    padding: '5px 0',
                    borderRadius: '6px',
                    border: 'none',
                    cursor: 'pointer',
                    backgroundColor: filterMode === 'all' ? 'var(--acc)' : 'transparent',
                    color: filterMode === 'all' ? '#fff' : 'var(--ink2)',
                  }}
                >
                  Tất cả
                </button>
                <button
                  onClick={() => setFilterMode('quen')}
                  style={{
                    flex: 1,
                    fontSize: '11.5px',
                    fontWeight: 600,
                    padding: '5px 0',
                    borderRadius: '6px',
                    border: 'none',
                    cursor: 'pointer',
                    backgroundColor: filterMode === 'quen' ? 'var(--okq)' : 'transparent',
                    color: filterMode === 'quen' ? 'var(--ok)' : 'var(--ink2)',
                  }}
                >
                  ✓ Xe quen
                </button>
                <button
                  onClick={() => setFilterMode('la')}
                  style={{
                    flex: 1,
                    fontSize: '11.5px',
                    fontWeight: 600,
                    padding: '5px 0',
                    borderRadius: '6px',
                    border: 'none',
                    cursor: 'pointer',
                    backgroundColor: filterMode === 'la' ? 'var(--p0q)' : 'transparent',
                    color: filterMode === 'la' ? 'var(--p0)' : 'var(--ink2)',
                  }}
                >
                  ⚠ Xe lạ
                </button>
              </div>

              {/* Search Bar */}
              <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <input
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                  placeholder="Tìm theo biển số, làn xe, giờ…"
                  style={{
                    width: '100%',
                    backgroundColor: 'var(--bg)',
                    border: '1px solid var(--line2)',
                    borderRadius: '8px',
                    padding: '6px 28px 6px 10px',
                    fontSize: '12px',
                    color: 'var(--ink)',
                    outline: 'none',
                  }}
                />
                {searchFilter && (
                  <button
                    onClick={() => setSearchFilter('')}
                    style={{
                      position: 'absolute',
                      right: '8px',
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--ink3)',
                      cursor: 'pointer',
                      fontSize: '11px',
                    }}
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Event List */}
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {filteredEvents.length === 0 ? (
              <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--ink3)', fontSize: '12px' }}>
                Không có dữ liệu biển số phù hợp
              </div>
            ) : (
              filteredEvents.map((ev) => {
                const isUnknown = ev.status === 'unknown';
                const isStranger = !isUnknown && labels[ev.plate] !== 'quen';
                const isHovered = hoveredEventId === ev.id || hoveredPlate === ev.plate;

                return (
                  <div
                    key={ev.id}
                    onMouseEnter={() => {
                      setHoveredEventId(ev.id);
                      setHoveredPlate(ev.plate);
                    }}
                    onMouseLeave={() => {
                      setHoveredEventId(null);
                      setHoveredPlate(null);
                    }}
                    style={{
                      padding: '12px 18px',
                      borderBottom: '1px solid var(--line)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      backgroundColor: isHovered ? 'var(--card-hover)' : 'transparent',
                      transition: 'background-color 0.15s ease',
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div
                        style={{
                          fontSize: '11px',
                          fontFamily: 'var(--font-mono)',
                          color: 'var(--ink3)',
                          minWidth: '38px',
                        }}
                      >
                        {ev.time}
                      </div>

                      {ev.cropPath ? (
                        <button
                          type="button"
                          title={`Xem ảnh crop biển số ${ev.plate}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedCrop({ plate: ev.plate, url: getCropImageUrl(ev.cropPath) });
                          }}
                          style={{
                            width: '46px',
                            height: '30px',
                            padding: 0,
                            border: '1px solid var(--line2)',
                            borderRadius: '5px',
                            overflow: 'hidden',
                            backgroundColor: 'var(--raise)',
                            cursor: 'pointer',
                            flexShrink: 0,
                          }}
                        >
                          <img
                            src={getCropImageUrl(ev.cropPath)}
                            alt={`Biển số ${ev.plate}`}
                            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                          />
                        </button>
                      ) : (
                        <div style={{ width: '46px', height: '30px', borderRadius: '5px', backgroundColor: 'var(--raise)' }} />
                      )}

                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span
                            style={{
                              fontFamily: 'var(--font-mono)',
                              fontWeight: 700,
                              fontSize: '13px',
                              color: isHovered ? 'var(--cyan)' : 'var(--ink)',
                            }}
                          >
                            {ev.plate}
                          </span>
                          {ev.conf !== null && (
                            <span
                              style={{
                                fontSize: '9.5px',
                                fontFamily: 'var(--font-mono)',
                                color: ev.conf > 90 ? 'var(--ok)' : 'var(--p1)',
                                backgroundColor: ev.conf > 90 ? 'var(--okq)' : 'var(--p1q)',
                                padding: '1px 5px',
                                borderRadius: '4px',
                                fontWeight: 600,
                              }}
                            >
                              {ev.conf}%
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--ink3)', marginTop: '2px' }}>
                          {ev.zone}
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span
                        style={{
                          fontSize: '10.5px',
                          fontWeight: 700,
                          padding: '3px 8px',
                          borderRadius: '12px',
                          backgroundColor: isUnknown ? 'var(--raise)' : (isStranger ? 'var(--p0q)' : 'var(--okq)'),
                          color: isUnknown ? 'var(--ink2)' : (isStranger ? 'var(--p0)' : 'var(--ok)'),
                          border: `1px solid ${isUnknown ? 'var(--line2)' : (isStranger ? 'var(--p0)' : 'var(--ok)')}`,
                        }}
                      >
                        {isUnknown ? 'Không xác định' : (isStranger ? 'Xe lạ' : 'Xe quen')}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
      {/* Toast Notification */}
      {toastMessage && (
        <div
          style={{
            position: 'fixed',
            bottom: '24px',
            right: '24px',
            backgroundColor: 'rgba(16, 185, 129, 0.95)',
            color: '#fff',
            padding: '10px 18px',
            borderRadius: '8px',
            fontSize: '13px',
            fontWeight: 600,
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.4)',
            zIndex: 200,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            animation: 'fadeIn 0.2s ease',
          }}
        >
          <span>✓</span>
          <span>{toastMessage}</span>
        </div>
      )}
      {selectedCrop && createPortal((
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Ảnh crop biển số ${selectedCrop.plate}`}
          onClick={() => setSelectedCrop(null)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 200,
            backgroundColor: 'rgba(0,0,0,0.72)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
          }}
        >
          <div
            className="glass-panel"
            onClick={(event) => event.stopPropagation()}
            style={{ width: 'min(680px, 100%)', padding: '12px', borderRadius: '8px' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <strong style={{ color: 'var(--ink)', fontFamily: 'var(--font-mono)' }}>{selectedCrop.plate}</strong>
              <button
                type="button"
                onClick={() => setSelectedCrop(null)}
                title="Đóng ảnh"
                aria-label="Đóng ảnh"
                style={{ border: 0, background: 'transparent', color: 'var(--ink)', cursor: 'pointer', fontSize: '20px' }}
              >
                ×
              </button>
            </div>
            <img
              src={selectedCrop.url}
              alt={`Ảnh crop biển số ${selectedCrop.plate}`}
              style={{ width: '100%', maxHeight: '70vh', objectFit: 'contain', display: 'block' }}
            />
          </div>
        </div>
      ), document.body)}
    </div>
  );
};
