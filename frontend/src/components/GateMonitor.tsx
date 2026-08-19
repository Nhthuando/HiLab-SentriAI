import React, { useState, useMemo, useEffect } from 'react';
import type { GateEvent, PolygonZone } from '../types';
import { useCameraFeed } from '../hooks/useCameraFeed';
import { useWebSocket } from '../hooks/useWebSocket';
import { getGateEvents } from '../api/events';

interface GateMonitorProps {
  clock: string;
  zones: PolygonZone[];
  events: GateEvent[];
  labels: Record<string, 'quen' | 'la'>;
}

export const GateMonitor: React.FC<GateMonitorProps> = ({ clock, zones, events: initialEvents, labels }) => {
  const [liveEvents, setLiveEvents] = useState<GateEvent[]>(initialEvents);
  const [hoveredEventId, setHoveredEventId] = useState<string | null>(null);
  const [hoveredPlate, setHoveredPlate] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<'all' | 'la' | 'quen'>('all');
  const [searchFilter, setSearchFilter] = useState<string>('');

  // 1. Live Video Feed from WebSocket proxy (/ws/feed/gate)
  const {
    frameImage,
    detections,
    fps,
    isOnline,
    statusText,
    reconnect: reconnectFeed,
  } = useCameraFeed('GATE-01');

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

  // 3. Real-time Event Push from WebSocket proxy (/ws/events/gate)
  useWebSocket<{ type: string; data: GateEvent }>({
    path: '/ws/events/gate',
    onMessage: (msg) => {
      if (msg?.data) {
        const newEv = msg.data;
        setLiveEvents((prev) => {
          // Avoid duplicate event IDs
          if (prev.some((e) => e.id === newEv.id)) return prev;
          return [newEv, ...prev];
        });
      }
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
        const isKnown = (labels[e.plate] || e.status) === 'quen';
        if (isKnown && e.plate !== '—') return false;
      } else if (filterMode === 'quen') {
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
            {frameImage ? (
              <img
                src={frameImage}
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

            {/* Top Floating Glass HUD Bar */}
            <div
              className="glass-panel"
              style={{
                position: 'absolute',
                left: '12px',
                right: '12px',
                top: '12px',
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
                  className={isOnline ? 'animate-live' : ''}
                  style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    backgroundColor: isOnline ? 'var(--p0)' : 'var(--ink3)',
                    display: 'inline-block',
                  }}
                />
                <span
                  style={{
                    fontSize: '11.5px',
                    fontWeight: 700,
                    color: isOnline ? 'var(--p0)' : 'var(--ink3)',
                    letterSpacing: '0.04em',
                  }}
                >
                  {isOnline ? 'TRỰC TIẾP' : 'NGOẠI TUYẾN'}
                </span>
                <span style={{ color: 'var(--line2)' }}>|</span>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#ffffff' }}>GATE-01 · Làn xe vào chính</span>
                <span
                  style={{
                    fontSize: '10.5px',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--ink3)',
                    backgroundColor: 'rgba(255,255,255,0.06)',
                    padding: '2px 6px',
                    borderRadius: '4px',
                  }}
                >
                  1080p · {fps.toFixed(0)} FPS
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '11.5px', fontFamily: 'var(--font-mono)', color: 'var(--ink)', fontWeight: 600 }}>
                  {clock}
                </span>
              </div>
            </div>

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
            {detections.map((det, idx) => {
              const [x1, y1, x2, y2] = det.bbox;
              const isNorm = x2 <= 1.0 && y2 <= 1.0;
              const isPct = !isNorm && x2 <= 100.0 && y2 <= 100.0;
              const leftPct = isNorm ? x1 * 100 : isPct ? x1 : (x1 / 1280) * 100;
              const topPct = isNorm ? y1 * 100 : isPct ? y1 : (y1 / 720) * 100;
              const widthPct = isNorm ? (x2 - x1) * 100 : isPct ? (x2 - x1) : ((x2 - x1) / 1280) * 100;
              const heightPct = isNorm ? (y2 - y1) * 100 : isPct ? (y2 - y1) : ((y2 - y1) / 720) * 100;

              const plateText = (det as any).plate || '';
              const isStranger = (det as any).lpr_status === 'STRANGER';
              const isBoxHovered = plateText && (hoveredPlate === plateText || hoveredEventId === plateText);

              return (
                <div
                  key={`det-${idx}`}
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
                const isStranger = (labels[ev.plate] || ev.status) === 'la';
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
                          backgroundColor: isStranger ? 'var(--p0q)' : 'var(--okq)',
                          color: isStranger ? 'var(--p0)' : 'var(--ok)',
                          border: `1px solid ${isStranger ? 'var(--p0)' : 'var(--ok)'}`,
                        }}
                      >
                        {isStranger ? 'Xe lạ' : 'Xe quen'}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
