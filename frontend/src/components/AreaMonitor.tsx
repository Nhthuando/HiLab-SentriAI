import React, { useState, useMemo, useRef } from 'react';
import type { PolygonZone } from '../types';
import { useAreaMonitor } from '../hooks/useAreaMonitor';

interface AreaMonitorProps {
  clock: string;
}

const formatTime = (secs: number) => {
  if (isNaN(secs) || secs < 0) return '00:00';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
};

export const AreaMonitor: React.FC<AreaMonitorProps> = ({ clock }) => {
  const {
    frameImage,
    detections,
    activeZones,
    fps,
    isOnline,
    statusText,
    reconnectFeed,
    playback,
    seekPlayback,
    violations,
    filteredEvents,
    filterMode,
    setFilterMode,
    searchFilter,
    setSearchFilter,
    hoveredEventId,
    setHoveredEventId,
    isLoadingRest,
    restError,
    fetchViolations,
    clearAreaEvents,
    requestEventClip,
    closeEventClip,
    selectedClip,
    kpis,
  } = useAreaMonitor();

  const [hoveredFeedObjectKey, setHoveredFeedObjectKey] = useState<string | null>(null);
  const clipVideoRef = useRef<HTMLVideoElement | null>(null);

  const closeClipModal = () => {
    const video = clipVideoRef.current;
    if (video) {
      video.pause();
      video.removeAttribute('src');
      video.load();
    }
    closeEventClip();
  };

  // Play / Pause & Seek timeline state
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [frozenFrame, setFrozenFrame] = useState<string | null>(null);
  const [frozenDetections, setFrozenDetections] = useState<typeof detections>([]);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [seekValue, setSeekValue] = useState<number>(0);
  const [seekPreview, setSeekPreview] = useState<string | null>(null);

  const displayFrame = seekPreview || (isPaused ? (frozenFrame || frameImage) : frameImage);
  const displayDetections = seekPreview ? [] : (isPaused ? frozenDetections : detections);

  const togglePause = () => {
    if (!isPaused) {
      setFrozenFrame(frameImage);
      setFrozenDetections(detections);
      setIsPaused(true);
    } else {
      setIsPaused(false);
    }
  };

  // Selected or hovered event
  const currentHoveredEvent = useMemo(() => {
    return filteredEvents.find((e) => e.id === hoveredEventId) || null;
  }, [filteredEvents, hoveredEventId]);

  // Derive dynamic rule chips from active zones
  const activeZoneForRules = useMemo(() => {
    if (currentHoveredEvent && currentHoveredEvent.zoneId) {
      const z = activeZones.find((item) => item.id === currentHoveredEvent.zoneId);
      if (z) return z;
    }
    return activeZones[0] || null;
  }, [activeZones, currentHoveredEvent]);

  const dynamicTypeRules = useMemo(() => {
    if (!activeZoneForRules) return [];

    const rules: Array<{ label: string; ok: boolean; icon: string }> = [];
    const iconForClass = (name: string) => {
      const n = name.toLowerCase();
      if (n.includes('máy') || n.includes('đạp')) return 'M5 17a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19 17a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8 14l3-5h4l3 5';
      if (n.includes('nâng')) return 'M5 18h9M5 18V8h5l2 4h4v6M18 18v-8';
      if (n.includes('container') || n.includes('tải')) return 'M3 16V8h11v8M14 10h4l3 3v3M6 19a1.5 1.5 0 1 0 0-3M17 19a1.5 1.5 0 1 0 0-3';
      return 'M5 16l1-5 2-3h8l2 3 1 5M5 16h14M7 19a1.5 1.5 0 1 0 0-3M17 19a1.5 1.5 0 1 0 0-3';
    };

    const labels = new Map<string, string>();
    for (const label of activeZoneForRules.targetLabels || []) {
      labels.set(label.toLocaleLowerCase(), label);
    }
    for (const detection of detections) {
      const isInActiveZone = detection.zoneMatches?.some(
        (match) => match.zoneId === activeZoneForRules.id,
      );
      const label = detection.label || detection.class;
      if (isInActiveZone && label) labels.set(label.toLocaleLowerCase(), label);
    }

    const targeted = new Set(
      (activeZoneForRules.targetLabels || []).map((label) => label.toLocaleLowerCase()),
    );
    for (const label of labels.values()) {
      const isTargeted = targeted.has(label.toLocaleLowerCase());
      const isAllowed = activeZoneForRules.ruleType === 'ALLOW_SPECIFIED'
        ? isTargeted
        : !isTargeted;
      rules.push({ label, ok: isAllowed, icon: iconForClass(label) });
    }

    return rules;
  }, [activeZoneForRules, detections]);

  // Robust zone match check for hover synchronization
  const isZoneMatchingHover = (zone: PolygonZone) => {
    if (!currentHoveredEvent) return false;
    return currentHoveredEvent.zoneId === zone.id;
  };

  // Robust object match check for hover synchronization
  const isDetectionMatchingHover = (det: typeof detections[0], index: number) => {
    const key = `det-${det.trackId ?? index}`;
    if (hoveredFeedObjectKey === key) return true;
    if (!currentHoveredEvent) return false;

    if (currentHoveredEvent.trackId !== undefined && currentHoveredEvent.trackId !== null) {
      if (det.trackId === currentHoveredEvent.trackId) return true;
    }

    return false;
  };

  const kpiCards = [
    {
      label: 'Đối tượng trong khu',
      value: String(kpis.objectsInZoneCount),
      sub: 'Đang hoạt động',
      color: 'var(--ink)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--acc)" strokeWidth="2">
          <circle cx="12" cy="10" r="10" />
          <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
          <path d="M2 12h20" />
        </svg>
      ),
    },
    {
      label: 'Vi phạm loại xe hôm nay',
      value: String(kpis.violationCount),
      sub: 'Cần xử lý nhắc nhở',
      color: 'var(--p0)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--p0)" strokeWidth="2">
          <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      ),
    },
    {
      label: 'Đối tượng được phép',
      value: String(kpis.allowedInZoneCount),
      sub: 'Hoạt động đúng quy định',
      color: 'var(--ok)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth="2">
          <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
          <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
        </svg>
      ),
    },
    {
      label: 'Zone khu vực giám sát',
      value: String(activeZones.length),
      sub: 'Đang kích hoạt quy tắc',
      color: 'var(--cyan)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" strokeWidth="2">
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px 32px', maxWidth: '1440px', margin: '0 auto', boxSizing: 'border-box' }}>
      {/* 4 KPI Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: '16px',
          marginBottom: '24px',
        }}
      >
        {kpiCards.map((kpi, idx) => (
          <div
            key={idx}
            className="glass-card"
            style={{
              borderRadius: '16px',
              padding: '18px 22px',
              boxShadow: 'var(--shadow-md)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div>
              <div style={{ fontSize: '12.5px', color: 'var(--ink2)', fontWeight: 600, marginBottom: '8px' }}>
                {kpi.label}
              </div>
              <div
                style={{
                  fontSize: '28px',
                  fontWeight: 800,
                  fontFamily: 'var(--font-mono)',
                  color: kpi.color,
                  letterSpacing: '-0.02em',
                  lineHeight: 1.1,
                }}
              >
                {kpi.value}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--ink3)', marginTop: '6px' }}>{kpi.sub}</div>
            </div>

            <div
              style={{
                width: '44px',
                height: '44px',
                borderRadius: '12px',
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--line2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              {kpi.icon}
            </div>
          </div>
        ))}
      </div>

      {/* Main Grid: Feed + Rules (Left) & Area Events (Right) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.6fr) minmax(360px, 1fr)',
          gap: '24px',
          alignItems: 'start',
        }}
      >
        {/* Left: Feed & Type Rules */}
        <div style={{ paddingTop: '54px' }}>
          <div
            style={{
              position: 'relative',
              width: '100%',
              // Worker frames and normalized zone/bbox coordinates are 640x480.
              // Keeping the same 4:3 canvas prevents visual coordinate drift.
              aspectRatio: '4 / 3',
              backgroundColor: '#07090c',
              border: '1px solid var(--line2)',
              borderRadius: '16px',
              overflow: 'visible',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            {/* Live Camera Feed Image */}
            {displayFrame ? (
              <img
                src={displayFrame}
                alt="Bãi kiểm camera live feed"
                style={{
                  position: 'absolute',
                  inset: 0,
                  width: '100%',
                  height: '100%',
                  objectFit: 'fill',
                  borderRadius: '15px',
                }}
              />
            ) : (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    borderRadius: '15px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: '#0c0f14',
                  color: 'var(--ink3)',
                  gap: '12px',
                }}
              >
                <div
                  className="animate-spin"
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    border: '3px solid var(--line2)',
                    borderTopColor: 'var(--acc)',
                  }}
                />
                <span style={{ fontSize: '13px' }}>Đang kết nối camera bãi kiểm (BAI-KIEM)...</span>
              </div>
            )}

            {/* Offline / Reconnect Overlay */}
            {!isOnline && (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  backgroundColor: 'rgba(12, 16, 24, 0.85)',
                  backdropFilter: 'blur(6px)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '12px',
                  zIndex: 30,
                }}
              >
                <span style={{ fontSize: '16px', fontWeight: 700, color: 'var(--p0)' }}>
                  ⚠️ {statusText || 'Mất kết nối camera'}
                </span>
                <button
                  onClick={reconnectFeed}
                  style={{
                    fontSize: '12px',
                    fontWeight: 600,
                    padding: '8px 18px',
                    borderRadius: '8px',
                    border: 'none',
                    backgroundColor: 'var(--acc)',
                    color: '#ffffff',
                    cursor: 'pointer',
                  }}
                >
                  Thử kết nối lại
                </button>
              </div>
            )}

            <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(5, 8, 12, 0.05)', pointerEvents: 'none' }} />

            {/* Top Floating Glass HUD Bar */}
            <div
              className="glass-panel"
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                top: '-54px',
                borderRadius: '10px',
                padding: '8px 14px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                zIndex: 20,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span
                  className="animate-live"
                  style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    backgroundColor: isPaused ? 'var(--p1)' : (isOnline ? 'var(--ok)' : 'var(--p0)'),
                    display: 'inline-block',
                  }}
                />
                <span
                  style={{
                    fontSize: '11.5px',
                    fontWeight: 700,
                    color: isPaused ? 'var(--p1)' : (isOnline ? 'var(--ok)' : 'var(--p0)'),
                    letterSpacing: '0.04em',
                  }}
                >
                  {isPaused ? 'TẠM DỪNG' : (isOnline ? 'TRỰC TIẾP' : 'MẤT KẾT NỐI')}
                </span>
                <span style={{ color: 'var(--line2)' }}>|</span>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#ffffff' }}>BAI-KIEM · Bãi kiểm bốc dỡ</span>
                <span
                  style={{
                    fontSize: '10.5px',
                    fontFamily: 'var(--font-mono)',
                    color: isPaused ? '#f59e0b' : 'var(--ink3)',
                    backgroundColor: isPaused ? 'rgba(245, 158, 11, 0.15)' : 'rgba(255,255,255,0.06)',
                    padding: '2px 6px',
                    borderRadius: '4px',
                  }}
                >
                  1280x720 · {isPaused ? 'TẠM DỪNG' : `${fps.toFixed(1)} FPS`}
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                {/* Play / Pause Toggle Button */}
                <button
                  onClick={togglePause}
                  title={isPaused ? "Tiếp tục phát video" : "Tạm dừng video để kiểm tra"}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '4px 10px',
                    borderRadius: '6px',
                    border: isPaused ? '1px solid var(--p1)' : '1px solid var(--line2)',
                    backgroundColor: isPaused ? 'rgba(245, 158, 11, 0.25)' : 'rgba(255, 255, 255, 0.1)',
                    color: isPaused ? 'var(--p1)' : '#ffffff',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {isPaused ? (
                    <>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                        <polygon points="5 3 19 12 5 21 5 3" />
                      </svg>
                      <span>Tiếp tục</span>
                    </>
                  ) : (
                    <>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                        <rect x="6" y="4" width="4" height="16" />
                        <rect x="14" y="4" width="4" height="16" />
                      </svg>
                      <span>Tạm dừng</span>
                    </>
                  )}
                </button>

                <span style={{ fontSize: '11.5px', fontFamily: 'var(--font-mono)', color: 'var(--ink)', fontWeight: 600 }}>
                  {clock}
                </span>
              </div>
            </div>

            {/* SVG Polygon Zones for BAI-KIEM */}
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
              {activeZones.map((zone) => {
                const pointsStr = zone.points.map((p) => `${p[0]},${p[1]}`).join(' ');
                const isZoneMatched = isZoneMatchingHover(zone);

                return (
                  <polygon
                    key={zone.id}
                    points={pointsStr}
                    fill={zone.color}
                    fillOpacity={isZoneMatched ? 0.35 : 0.14}
                    stroke={isZoneMatched ? '#ffffff' : zone.color}
                    strokeWidth={isZoneMatched ? '3' : '1.8'}
                    strokeDasharray={isZoneMatched ? '0' : '6 4'}
                    vectorEffect="non-scaling-stroke"
                    style={{
                      transition: 'all 0.18s ease',
                      filter: isZoneMatched ? `drop-shadow(0 0 8px ${zone.color})` : 'none',
                    }}
                  />
                );
              })}
            </svg>

            {/* Zone Labels (centered) */}
            {activeZones.map((zone) => {
              if (!zone.points || zone.points.length === 0) return null;
              const centerX = zone.points.reduce((acc, p) => acc + p[0], 0) / zone.points.length;
              const centerY = zone.points.reduce((acc, p) => acc + p[1], 0) / zone.points.length;
              const isZoneMatched = isZoneMatchingHover(zone);

              return (
                <span
                  key={`label-${zone.id}`}
                  style={{
                    position: 'absolute',
                    left: `${centerX.toFixed(1)}%`,
                    top: `${centerY.toFixed(1)}%`,
                    transform: isZoneMatched ? 'translate(-50%, -50%) scale(1.1)' : 'translate(-50%, -50%) scale(1)',
                    fontSize: '10.5px',
                    fontWeight: 700,
                    color: '#ffffff',
                    backgroundColor: 'rgba(15, 23, 42, 0.78)',
                    border: `1px solid ${zone.color}`,
                    padding: '3px 8px',
                    borderRadius: '6px',
                    backdropFilter: 'blur(6px)',
                    boxShadow: isZoneMatched
                      ? `0 0 16px rgba(255,255,255,0.8), 0 0 8px ${zone.color}`
                      : '0 2px 8px rgba(0,0,0,0.5)',
                    whiteSpace: 'nowrap',
                    pointerEvents: 'none',
                    letterSpacing: '0.04em',
                    transition: 'all 0.18s ease',
                    zIndex: 8,
                  }}
                >
                  {zone.name.toUpperCase()}
                </span>
              );
            })}

            {/* Real-Time Detected Objects with Bounding Boxes */}
            {displayDetections.map((det, idx) => {
              const key = `det-${det.trackId ?? idx}`;
              const isHighlighted = isDetectionMatchingHover(det, idx);

              // Coordinates from normalized_bbox or fallback
              let bx = '0%';
              let by = '0%';
              let bw = '0%';
              let bh = '0%';

              if (det.normalized_bbox && det.normalized_bbox.length >= 4) {
                const [nx1, ny1, nx2, ny2] = det.normalized_bbox;
                bx = `${(nx1 * 100).toFixed(2)}%`;
                by = `${(ny1 * 100).toFixed(2)}%`;
                bw = `${((nx2 - nx1) * 100).toFixed(2)}%`;
                bh = `${((ny2 - ny1) * 100).toFixed(2)}%`;
              } else if (det.bbox && det.bbox.length >= 4) {
                const [x1, y1, x2, y2] = det.bbox;
                bx = `${((x1 / 640) * 100).toFixed(2)}%`;
                by = `${((y1 / 480) * 100).toFixed(2)}%`;
                bw = `${(((x2 - x1) / 640) * 100).toFixed(2)}%`;
                bh = `${(((y2 - y1) / 480) * 100).toFixed(2)}%`;
              }

              const isOutside = det.status === 'OUTSIDE' || !det.zoneMatches?.length;
              const isViolation = !isOutside && det.status === 'VIOLATION';
              const color = isOutside ? '#94a3b8' : isViolation ? '#f43f5e' : '#10b981';
              const fill = isOutside
                ? 'rgba(148,163,184,0.10)'
                : isViolation
                  ? 'rgba(244,63,94,0.22)'
                  : 'rgba(16,185,129,0.12)';
              const statusText = isOutside ? 'NGOÀI ZONE' : isViolation ? 'VI PHẠM ZONE' : 'ĐƯỢC PHÉP';
              const labelText = `${(det.label || det.class).toUpperCase()} · ${statusText}`;

              return (
                <div
                  key={key}
                  onMouseEnter={() => setHoveredFeedObjectKey(key)}
                  onMouseLeave={() => setHoveredFeedObjectKey(null)}
                  style={{
                    position: 'absolute',
                    left: bx,
                    top: by,
                    width: bw,
                    height: bh,
                    border: `${isHighlighted ? '2.5px' : '1.8px'} solid ${isHighlighted ? '#ffffff' : color}`,
                    backgroundColor: isHighlighted ? `${color}45` : fill,
                    boxShadow: isHighlighted
                      ? `0 0 24px ${color}, 0 0 12px #ffffff`
                      : isViolation
                      ? '0 0 12px rgba(244,63,94,0.4)'
                      : 'none',
                    borderRadius: '4px',
                    transform: isHighlighted ? 'scale(1.04)' : 'scale(1)',
                    transition: 'all 0.18s cubic-bezier(0.16, 1, 0.3, 1)',
                    cursor: 'pointer',
                    zIndex: isHighlighted ? 15 : 10,
                  }}
                >
                  <span
                    style={{
                      position: 'absolute',
                      left: '-1px',
                      top: '-22px',
                      backgroundColor: isHighlighted ? '#ffffff' : color,
                      color: isHighlighted ? '#000000' : '#ffffff',
                      fontSize: '9.5px',
                      fontWeight: 700,
                      padding: '2px 8px',
                      borderRadius: '4px',
                      whiteSpace: 'nowrap',
                      boxShadow: isHighlighted
                        ? '0 0 14px rgba(255,255,255,0.9), 0 2px 8px rgba(0,0,0,0.5)'
                        : '0 2px 8px rgba(0,0,0,0.5)',
                      transform: isHighlighted ? 'scale(1.08)' : 'scale(1)',
                      transformOrigin: 'bottom left',
                      transition: 'all 0.18s ease',
                    }}
                  >
                    {labelText}
                  </span>
                </div>
              );
              })}
          </div>

          {/* Timeline & Video Playback Scrub Bar (When camera source is a video file) */}
          {playback?.seekable && (
            <div
              className="glass-card"
              style={{
                marginTop: '12px',
                padding: '10px 14px',
                borderRadius: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                backgroundColor: 'var(--panel)',
                border: '1px solid var(--line2)',
              }}
            >
              {/* Quick Jump Back -10s */}
              <button
                onClick={() => {
                  const target = Math.max(0, (playback.positionSeconds || 0) - 10);
                  seekPlayback(target);
                }}
                title="Lùi 10 giây"
                style={{
                  background: 'rgba(255, 255, 255, 0.06)',
                  border: '1px solid var(--line2)',
                  color: 'var(--ink2)',
                  borderRadius: '6px',
                  padding: '4px 8px',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                -10s
              </button>

              {/* Play / Pause Toggle Button */}
              <button
                onClick={togglePause}
                style={{
                  background: isPaused ? 'rgba(245, 158, 11, 0.25)' : 'var(--acc)',
                  border: isPaused ? '1px solid var(--p1)' : 'none',
                  color: isPaused ? 'var(--p1)' : '#ffffff',
                  borderRadius: '6px',
                  padding: '5px 12px',
                  fontSize: '12px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  whiteSpace: 'nowrap',
                }}
              >
                {isPaused ? '▶ Tiếp tục' : '⏸ Tạm dừng'}
              </button>

              {/* Quick Jump Forward +10s */}
              <button
                onClick={() => {
                  const target = Math.min(playback.durationSeconds || 100, (playback.positionSeconds || 0) + 10);
                  seekPlayback(target);
                }}
                title="Tua 10 giây"
                style={{
                  background: 'rgba(255, 255, 255, 0.06)',
                  border: '1px solid var(--line2)',
                  color: 'var(--ink2)',
                  borderRadius: '6px',
                  padding: '4px 8px',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                +10s
              </button>

              {/* Time Display */}
              <span
                style={{
                  fontSize: '12px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--ink2)',
                  minWidth: '95px',
                  fontWeight: 600,
                  textAlign: 'center',
                }}
              >
                {formatTime(isDragging ? seekValue : (playback.positionSeconds || 0))} / {formatTime(playback.durationSeconds || 0)}
              </span>

              {/* Scrub Slider */}
              <input
                type="range"
                min={0}
                max={playback.durationSeconds || 100}
                step={0.5}
                value={isDragging ? seekValue : (playback.positionSeconds || 0)}
                onMouseDown={() => {
                  setIsDragging(true);
                  setSeekValue(playback.positionSeconds || 0);
                }}
                onTouchStart={() => {
                  setIsDragging(true);
                  setSeekValue(playback.positionSeconds || 0);
                }}
                onChange={(e) => {
                  setSeekValue(parseFloat(e.target.value));
                }}
                onMouseUp={() => {
                  setIsDragging(false);
                  void seekPlayback(seekValue);
                  setSeekPreview(null);
                }}
                onTouchEnd={() => {
                  setIsDragging(false);
                  void seekPlayback(seekValue);
                  setSeekPreview(null);
                }}
                style={{
                  flex: 1,
                  accentColor: 'var(--acc)',
                  cursor: 'pointer',
                  height: '6px',
                }}
              />
            </div>
          )}

          {/* Type Rule Chips */}
          <div style={{ display: 'flex', gap: '8px', marginTop: '14px', flexWrap: 'wrap' }}>
            {dynamicTypeRules.map((rule, idx) => (
              <span
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '11.5px',
                  fontWeight: 600,
                  padding: '6px 13px',
                  borderRadius: '20px',
                  border: `1px solid ${rule.ok ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`,
                  backgroundColor: rule.ok ? 'var(--okq)' : 'var(--p0q)',
                  color: rule.ok ? 'var(--ok)' : 'var(--p0)',
                }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                  <path d={rule.icon} />
                </svg>
                {rule.ok ? rule.label : `✕ ${rule.label}`}
              </span>
            ))}
          </div>
        </div>

        {/* Right: Area Events List with Filter & Search */}
        <div
          className="glass-panel"
          style={{
            borderRadius: '16px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            maxHeight: '620px',
            boxShadow: 'var(--shadow-lg)',
          }}
        >
          {/* Panel Header */}
          <div
            style={{
              padding: '16px 20px',
              borderBottom: '1px solid var(--line)',
              backgroundColor: 'var(--panel)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '14.5px', fontWeight: 700, color: 'var(--ink)' }}>Sự kiện khu vực</span>
                <span
                  style={{
                    fontSize: '11.5px',
                    fontWeight: 600,
                    padding: '2px 8px',
                    borderRadius: '12px',
                    backgroundColor: 'var(--raise)',
                    color: 'var(--ink2)',
                  }}
                >
                  {filteredEvents.length} sự kiện
                </span>
              </div>

              {/* Clear all events button */}
              <button
                onClick={async () => {
                  if (window.confirm('Bạn có chắc chắn muốn xóa toàn bộ sự kiện và các video clip đã lưu để giải phóng dung lượng?')) {
                    const ok = await clearAreaEvents();
                    if (ok) alert('Đã xóa toàn bộ sự kiện thành công!');
                  }
                }}
                title="Xóa toàn bộ sự kiện & giải phóng dung lượng video clip"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '4px 10px',
                  borderRadius: '6px',
                  border: '1px solid rgba(244, 63, 94, 0.35)',
                  backgroundColor: 'rgba(244, 63, 94, 0.12)',
                  color: '#f43f5e',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
                <span>Xóa tất cả</span>
              </button>
            </div>

            {/* Filter Pills */}
            <div style={{ display: 'flex', gap: '6px', marginBottom: '12px' }}>
              <button
                onClick={() => setFilterMode('all')}
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  padding: '6px 13px',
                  borderRadius: '8px',
                  border: filterMode === 'all' ? '1px solid rgba(59, 130, 246, 0.3)' : '1px solid transparent',
                  cursor: 'pointer',
                  backgroundColor: filterMode === 'all' ? 'var(--acc)' : 'var(--raise)',
                  color: filterMode === 'all' ? '#fff' : 'var(--ink2)',
                  transition: 'all 0.15s ease',
                }}
              >
                Tất cả
              </button>
              <button
                onClick={() => setFilterMode('violation')}
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  padding: '6px 13px',
                  borderRadius: '8px',
                  border: filterMode === 'violation' ? '1px solid var(--p0)' : '1px solid transparent',
                  cursor: 'pointer',
                  backgroundColor: filterMode === 'violation' ? 'var(--p0q)' : 'var(--raise)',
                  color: filterMode === 'violation' ? 'var(--p0)' : 'var(--ink2)',
                  transition: 'all 0.15s ease',
                }}
              >
                ⚠ Vi phạm ({violations.length})
              </button>
              <button
                onClick={() => setFilterMode('ok')}
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  padding: '6px 13px',
                  borderRadius: '8px',
                  border: filterMode === 'ok' ? '1px solid var(--ok)' : '1px solid transparent',
                  cursor: 'pointer',
                  backgroundColor: filterMode === 'ok' ? 'var(--okq)' : 'var(--raise)',
                  color: filterMode === 'ok' ? 'var(--ok)' : 'var(--ink2)',
                  transition: 'all 0.15s ease',
                }}
              >
                ✓ Được phép
              </button>
            </div>

            {/* Quick Search */}
            <div style={{ position: 'relative' }}>
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--ink3)"
                strokeWidth="2"
                style={{ position: 'absolute', left: '11px', top: '50%', transform: 'translateY(-50%)' }}
              >
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3" />
              </svg>
              <input
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                placeholder="Lọc nhanh đối tượng, zone..."
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  backgroundColor: 'var(--bg)',
                  border: '1px solid var(--line2)',
                  borderRadius: '8px',
                  padding: '8px 12px 8px 34px',
                  fontSize: '12.5px',
                  color: 'var(--ink)',
                  outline: 'none',
                }}
              />
            </div>
          </div>

          {/* Events Stream List */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {isLoadingRest && filteredEvents.length === 0 ? (
              <div style={{ padding: '36px 20px', textAlign: 'center', color: 'var(--ink3)', fontSize: '13px' }}>
                Đang tải dữ liệu sự kiện...
              </div>
            ) : restError && filteredEvents.length === 0 ? (
              <div style={{ padding: '36px 20px', textAlign: 'center', color: 'var(--p0)', fontSize: '13px' }}>
                {restError}
                <button
                  onClick={fetchViolations}
                  style={{
                    display: 'block',
                    margin: '10px auto 0',
                    padding: '6px 14px',
                    borderRadius: '8px',
                    border: '1px solid var(--line2)',
                    backgroundColor: 'var(--raise)',
                    color: 'var(--ink)',
                    cursor: 'pointer',
                  }}
                >
                  Thử lại
                </button>
              </div>
            ) : filteredEvents.length === 0 ? (
              <div style={{ padding: '36px 20px', textAlign: 'center', color: 'var(--ink3)', fontSize: '13px' }}>
                Không có sự kiện phù hợp bộ lọc
              </div>
            ) : (
              filteredEvents.map((event) => {
                const isOk = event.ok;
                const isHovered = hoveredEventId === event.id;

                return (
                  <div
                    key={event.id}
                    onMouseEnter={() => setHoveredEventId(event.id)}
                    onMouseLeave={() => setHoveredEventId(null)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '16px',
                      padding: '13px 20px',
                      borderBottom: '1px solid var(--line)',
                      backgroundColor: isHovered ? 'var(--card-hover)' : 'transparent',
                      borderLeft: isHovered ? `3px solid ${isOk ? 'var(--ok)' : 'var(--p0)'}` : '3px solid transparent',
                      transition: 'all 0.16s ease',
                      cursor: 'pointer',
                      boxSizing: 'border-box',
                    }}
                  >
                    <span
                      style={{
                        fontSize: '11.5px',
                        color: 'var(--ink3)',
                        fontFamily: 'var(--font-mono)',
                        width: '68px',
                        minWidth: '68px',
                        flexShrink: 0,
                        letterSpacing: '-0.01em',
                      }}
                    >
                      {event.time}
                    </span>

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontSize: '13.5px',
                          fontWeight: 600,
                          color: isHovered ? (isOk ? 'var(--ok)' : 'var(--p0)') : 'var(--ink)',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          lineHeight: 1.3,
                        }}
                      >
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{event.obj}</span>
                        {event.durationSeconds !== undefined && event.durationSeconds !== null && (
                          <span style={{ fontSize: '11px', color: 'var(--ink3)', fontWeight: 400, flexShrink: 0 }}>
                            ({event.durationSeconds === 0 ? '<1s' : `${event.durationSeconds}s`})
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--ink3)', marginTop: '3px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {event.zone}
                      </div>
                    </div>

                    {event.source === 'violation' && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void requestEventClip(event.id);
                        }}
                        disabled={
                          selectedClip?.eventId === event.id
                          && (selectedClip.status === 'QUEUED' || selectedClip.status === 'GENERATING')
                        }
                        title="Chỉ tạo và tải video khi bấm nút này"
                        style={{
                          border: 'none',
                          backgroundColor: 'rgba(255, 255, 255, 0.08)',
                          color: 'var(--ink2)',
                          padding: '5px 10px',
                          borderRadius: '6px',
                          cursor: selectedClip?.eventId === event.id
                            && (selectedClip.status === 'QUEUED' || selectedClip.status === 'GENERATING')
                            ? 'wait'
                            : 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px',
                          fontSize: '11px',
                          fontWeight: 600,
                          flexShrink: 0,
                          opacity: selectedClip?.eventId === event.id
                            && (selectedClip.status === 'QUEUED' || selectedClip.status === 'GENERATING')
                            ? 0.7
                            : 1,
                        }}
                      >
                        {selectedClip?.eventId === event.id
                          && (selectedClip.status === 'QUEUED' || selectedClip.status === 'GENERATING')
                          ? 'Đang tạo video…'
                          : '▶ Xem video'}
                      </button>
                    )}

                    <span
                      style={{
                        fontSize: '10.5px',
                        fontWeight: 700,
                        padding: '4px 11px',
                        borderRadius: '20px',
                        backgroundColor: isOk ? 'var(--okq)' : 'var(--p0q)',
                        color: isOk ? 'var(--ok)' : 'var(--p0)',
                        border: `1px solid ${isOk ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`,
                        flexShrink: 0,
                      }}
                    >
                      {event.st}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Video Clip Modal */}
      {selectedClip && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 150,
          }}
          onClick={closeClipModal}
        >
          <div
            style={{
              backgroundColor: 'var(--panel)',
              border: '1px solid var(--line2)',
              borderRadius: '16px',
              padding: '16px',
              maxWidth: '640px',
              width: '90%',
              boxShadow: 'var(--shadow-xl)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontSize: '14px', fontWeight: 700 }}>Video Clip 10s sự kiện</span>
              <button
                onClick={closeClipModal}
                style={{
                  border: 'none',
                  backgroundColor: 'transparent',
                  color: 'var(--ink2)',
                  cursor: 'pointer',
                  fontSize: '16px',
                }}
              >
                ✕
              </button>
            </div>
            {(selectedClip.status === 'QUEUED' || selectedClip.status === 'GENERATING') && (
              <div style={{ padding: '42px 20px', textAlign: 'center', color: 'var(--ink2)' }}>
                Đang tạo video 10 giây theo yêu cầu…
              </div>
            )}
            {selectedClip.status === 'READY' && selectedClip.url && (
              <video
                ref={clipVideoRef}
                src={selectedClip.url}
                controls
                autoPlay
                preload="metadata"
                style={{ width: '100%', borderRadius: '8px', backgroundColor: '#000' }}
              />
            )}
            {selectedClip.status === 'EXPIRED' && (
              <div style={{ padding: '36px 20px', textAlign: 'center', color: 'var(--p1)' }}>
                Video trực tiếp này đã quá thời gian lưu tạm 2 giờ nên không thể tạo lại.
              </div>
            )}
            {selectedClip.status === 'FAILED' && (
              <div style={{ padding: '36px 20px', textAlign: 'center', color: 'var(--p0)' }}>
                {selectedClip.message || 'Không thể tạo video cho sự kiện này. Hãy thử lại.'}
              </div>
            )}
            {selectedClip.status === 'NOT_REQUESTED' && (
              <div style={{ padding: '36px 20px', textAlign: 'center', color: 'var(--ink2)' }}>
                Video chưa được yêu cầu tạo.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
