import React, { useState, useMemo } from 'react';
import type { GateEvent, PolygonZone } from '../types';

interface GateMonitorProps {
  clock: string;
  zones: PolygonZone[];
  events: GateEvent[];
  labels: Record<string, 'quen' | 'la'>;
}

export const GateMonitor: React.FC<GateMonitorProps> = ({ clock, zones, events, labels }) => {
  const [hoveredEventId, setHoveredEventId] = useState<string | null>(null);
  const [hoveredPlate, setHoveredPlate] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<'all' | 'la' | 'quen'>('all');
  const [searchFilter, setSearchFilter] = useState<string>('');

  const unreadCount = events.filter((e) => e.conf === null).length;
  const readCount = events.length - unreadCount;

  const kpis = [
    {
      label: 'Lượt xe qua cổng',
      value: String(events.length),
      sub: 'Hôm nay',
      color: 'var(--ink)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--acc)" strokeWidth="2">
          <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.5 2.8C2.1 10.9 2 11.2 2 11.5V16c0 .6.4 1 1 1h2" />
          <circle cx="7" cy="17" r="2" />
          <path d="M9 17h6" />
          <circle cx="17" cy="17" r="2" />
        </svg>
      )
    },
    {
      label: 'Biển số đọc thành công',
      value: String(readCount),
      sub: `${((readCount / events.length) * 100).toFixed(0)}% tổng số lượt`,
      color: 'var(--ok)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      )
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
      )
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
      )
    }
  ];

  // Filter events
  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      // 1. Status Filter
      if (filterMode === 'la') {
        if (labels[e.plate] === 'quen' && e.plate !== '—') return false;
      } else if (filterMode === 'quen') {
        if (labels[e.plate] !== 'quen') return false;
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
  }, [events, labels, filterMode, searchFilter]);

  const isCurrentLivePlateHovered = hoveredPlate === '15R-158.45';

  return (
    <div style={{ padding: '24px', maxWidth: '1420px', margin: '0 auto' }}>
      {/* 4 KPI Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: '14px',
          marginBottom: '20px'
        }}
      >
        {kpis.map((kpi, idx) => (
          <div
            key={idx}
            className="glass-card"
            style={{
              borderRadius: '16px',
              padding: 'var(--kpi-py, 16px) var(--kpi-px, 20px)',
              boxShadow: 'var(--shadow-md)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              position: 'relative',
              overflow: 'hidden'
            }}
          >
            <div>
              <div style={{ fontSize: '12px', color: 'var(--ink3)', fontWeight: 500, marginBottom: '6px' }}>
                {kpi.label}
              </div>
              <div
                style={{
                  fontSize: '26px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  color: kpi.color,
                  letterSpacing: '-0.02em',
                  lineHeight: 1.1
                }}
              >
                {kpi.value}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--ink3)', marginTop: '5px' }}>{kpi.sub}</div>
            </div>

            <div
              style={{
                width: '42px',
                height: '42px',
                borderRadius: '12px',
                backgroundColor: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid var(--line)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 'none'
              }}
            >
              {kpi.icon}
            </div>
          </div>
        ))}
      </div>

      {/* Main Grid: Live Feed (left) & Event Panel (right) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.58fr) minmax(360px, 1fr)',
          gap: '18px',
          alignItems: 'start'
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
              boxShadow: 'var(--shadow-lg)'
            }}
          >
            {/* Background Camera Frame */}
            <div
              style={{
                position: 'absolute',
                inset: 0,
                backgroundImage: `url('/assets/cam-gate.png')`,
                backgroundSize: 'cover',
                backgroundPosition: 'center'
              }}
            />
            <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(5, 8, 12, 0.08)' }} />

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
                zIndex: 20
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span
                  className="animate-live"
                  style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    backgroundColor: 'var(--p0)',
                    display: 'inline-block'
                  }}
                />
                <span style={{ fontSize: '11.5px', fontWeight: 700, color: 'var(--p0)', letterSpacing: '0.04em' }}>
                  TRỰC TIẾP
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
                    borderRadius: '4px'
                  }}
                >
                  1080p · 25 FPS
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
                pointerEvents: 'none'
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
                    letterSpacing: '0.04em'
                  }}
                >
                  {zone.name.toUpperCase()}
                </span>
              );
            })}

            {/* LPR Detected License Plate Bounding Box (Modern Glass HUD Bracket) */}
            <div
              onMouseEnter={() => setHoveredPlate('15R-158.45')}
              onMouseLeave={() => setHoveredPlate(null)}
              style={{
                position: 'absolute',
                left: '78.5%',
                top: '79%',
                width: '6.5%',
                height: '7.5%',
                border: `2px solid ${isCurrentLivePlateHovered ? '#ffffff' : 'var(--cyan)'}`,
                backgroundColor: isCurrentLivePlateHovered ? 'rgba(6, 182, 212, 0.35)' : 'var(--cyanq)',
                borderRadius: '4px',
                boxShadow: isCurrentLivePlateHovered
                  ? '0 0 24px var(--cyan-glow), 0 0 10px #ffffff'
                  : '0 0 12px var(--cyan-glow)',
                transform: isCurrentLivePlateHovered ? 'scale(1.06)' : 'scale(1)',
                transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                cursor: 'pointer',
                zIndex: 15
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: '50%',
                  top: '-26px',
                  transform: 'translateX(-50%)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  backgroundColor: isCurrentLivePlateHovered ? '#ffffff' : '#0e1726',
                  color: isCurrentLivePlateHovered ? '#000000' : '#ffffff',
                  border: `1.5px solid ${isCurrentLivePlateHovered ? '#ffffff' : 'var(--cyan)'}`,
                  fontSize: '10.5px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  padding: '2px 8px',
                  borderRadius: '5px',
                  whiteSpace: 'nowrap',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.5)'
                }}
              >
                <span>15R-158.45</span>
                <span
                  style={{
                    fontSize: '9px',
                    padding: '1px 4px',
                    borderRadius: '3px',
                    backgroundColor: 'var(--ok)',
                    color: '#ffffff'
                  }}
                >
                  97%
                </span>
              </div>
            </div>
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
              padding: '0 4px'
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '3px', border: '1.8px solid var(--cyan)', backgroundColor: 'var(--cyanq)' }} />
              Khung biển số nhận diện (Hover để làm nổi bật)
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '3px', border: '1.5px dashed var(--ok)', backgroundColor: 'var(--okq)' }} />
              Zone làn vào (Đang giám sát)
            </span>
          </div>
        </div>

        {/* Right: Recognized Plates List with Filter & Search */}
        <div
          className="glass-panel"
          style={{
            borderRadius: '16px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            maxHeight: '610px',
            boxShadow: 'var(--shadow-lg)'
          }}
        >
          {/* Panel Header */}
          <div
            style={{
              padding: '14px 18px',
              borderBottom: '1px solid var(--line)',
              backgroundColor: 'var(--panel)'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--ink)' }}>Biển số đã nhận diện</span>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    padding: '2px 7px',
                    borderRadius: '12px',
                    backgroundColor: 'var(--raise)',
                    color: 'var(--ink2)'
                  }}
                >
                  {filteredEvents.length} sự kiện
                </span>
              </div>
            </div>

            {/* Filter Pills */}
            <div style={{ display: 'flex', gap: '5px', marginBottom: '10px' }}>
              <button
                onClick={() => setFilterMode('all')}
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  padding: '5px 12px',
                  borderRadius: '8px',
                  border: filterMode === 'all' ? '1px solid rgba(59, 130, 246, 0.3)' : '1px solid transparent',
                  cursor: 'pointer',
                  backgroundColor: filterMode === 'all' ? 'var(--acc)' : 'var(--raise)',
                  color: filterMode === 'all' ? '#fff' : 'var(--ink2)'
                }}
              >
                Tất cả
              </button>
              <button
                onClick={() => setFilterMode('la')}
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  padding: '5px 12px',
                  borderRadius: '8px',
                  border: filterMode === 'la' ? '1px solid var(--p0)' : '1px solid transparent',
                  cursor: 'pointer',
                  backgroundColor: filterMode === 'la' ? 'var(--p0q)' : 'var(--raise)',
                  color: filterMode === 'la' ? 'var(--p0)' : 'var(--ink2)'
                }}
              >
                ⚠ Xe lạ ({events.filter((e) => labels[e.plate] === 'la').length})
              </button>
              <button
                onClick={() => setFilterMode('quen')}
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  padding: '5px 12px',
                  borderRadius: '8px',
                  border: filterMode === 'quen' ? '1px solid var(--ok)' : '1px solid transparent',
                  cursor: 'pointer',
                  backgroundColor: filterMode === 'quen' ? 'var(--okq)' : 'var(--raise)',
                  color: filterMode === 'quen' ? 'var(--ok)' : 'var(--ink2)'
                }}
              >
                ✓ Xe quen
              </button>
            </div>

            {/* Quick Search */}
            <div style={{ position: 'relative' }}>
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--ink3)"
                strokeWidth="2"
                style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }}
              >
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3" />
              </svg>
              <input
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                placeholder="Lọc nhanh biển số, làn xe..."
                style={{
                  width: '100%',
                  backgroundColor: 'var(--bg)',
                  border: '1px solid var(--line2)',
                  borderRadius: '8px',
                  padding: '7px 10px 7px 30px',
                  fontSize: '12px',
                  color: 'var(--ink)',
                  outline: 'none'
                }}
              />
            </div>
          </div>

          {/* Event Stream List */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filteredEvents.length === 0 ? (
              <div style={{ padding: '32px 18px', textAlign: 'center', color: 'var(--ink3)', fontSize: '12.5px' }}>
                Không có sự kiện phù hợp bộ lọc
              </div>
            ) : (
              filteredEvents.map((event) => {
                const isRegistered = labels[event.plate] === 'quen';
                const isRowHovered = hoveredEventId === event.id;
                const confText = event.conf !== null ? `${event.conf}%` : 'Không đọc được';
                const confColor = event.conf === null ? 'var(--p1)' : event.conf >= 95 ? 'var(--ok)' : 'var(--p1)';

                return (
                  <div
                    key={event.id}
                    onMouseEnter={() => {
                      setHoveredEventId(event.id);
                      setHoveredPlate(event.plate);
                    }}
                    onMouseLeave={() => {
                      setHoveredEventId(null);
                      setHoveredPlate(null);
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '14px',
                      padding: 'var(--event-py, 12px) var(--event-px, 18px)',
                      borderBottom: '1px solid var(--line)',
                      backgroundColor: isRowHovered ? 'var(--card-hover)' : 'transparent',
                      borderLeft: isRowHovered ? '3px solid var(--cyan)' : '3px solid transparent',
                      transition: 'all 0.16s ease',
                      cursor: 'pointer'
                    }}
                  >
                    <span
                      style={{
                        fontSize: '11.5px',
                        color: 'var(--ink3)',
                        fontFamily: 'var(--font-mono)',
                        width: '44px',
                        flex: 'none'
                      }}
                    >
                      {event.time}
                    </span>

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {event.plate !== '—' ? (
                          <span
                            style={{
                              fontFamily: 'var(--font-mono)',
                              fontWeight: 700,
                              fontSize: '13px',
                              color: isRowHovered ? 'var(--cyan)' : 'var(--ink)',
                              letterSpacing: '0.02em'
                            }}
                          >
                            {event.plate}
                          </span>
                        ) : (
                          <span style={{ fontSize: '12.5px', color: 'var(--ink3)', fontStyle: 'italic' }}>
                            Không nhận dạng
                          </span>
                        )}

                        {event.plate !== '—' && (
                          <span
                            style={{
                              fontSize: '9.5px',
                              fontWeight: 700,
                              padding: '1.5px 7px',
                              borderRadius: '4px',
                              backgroundColor: isRegistered ? 'var(--okq)' : 'var(--p0q)',
                              color: isRegistered ? 'var(--ok)' : 'var(--p0)',
                              border: `1px solid ${isRegistered ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`
                            }}
                          >
                            {isRegistered ? 'XE QUEN' : 'XE LẠ'}
                          </span>
                        )}
                      </div>

                      <div style={{ fontSize: '11.5px', color: 'var(--ink3)', marginTop: '3px' }}>{event.zone}</div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 'none' }}>
                      <span
                        style={{
                          width: '6px',
                          height: '6px',
                          borderRadius: '50%',
                          backgroundColor: confColor
                        }}
                      />
                      <span
                        style={{
                          fontSize: '11.5px',
                          fontWeight: 600,
                          fontFamily: 'var(--font-mono)',
                          color: confColor
                        }}
                      >
                        {confText}
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
