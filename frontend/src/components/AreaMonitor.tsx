import React, { useState, useMemo } from 'react';
import type { AreaEvent, PolygonZone } from '../types';

interface AreaMonitorProps {
  clock: string;
  zones: PolygonZone[];
  events: AreaEvent[];
}

export const AreaMonitor: React.FC<AreaMonitorProps> = ({ clock, zones, events }) => {
  const [hoveredEventId, setHoveredEventId] = useState<string | null>(null);
  const [hoveredFeedObjectKey, setHoveredFeedObjectKey] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<'all' | 'violation' | 'ok'>('all');
  const [searchFilter, setSearchFilter] = useState<string>('');

  const violationCount = events.filter((e) => !e.ok).length;

  const kpis = [
    {
      label: 'Đối tượng trong khu',
      value: '4',
      sub: 'Đang hoạt động',
      color: 'var(--ink)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--acc)" strokeWidth="2">
          <circle cx="12" cy="10" r="10" />
          <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
          <path d="M2 12h20" />
        </svg>
      )
    },
    {
      label: 'Vi phạm loại xe hôm nay',
      value: String(violationCount),
      sub: 'Cần xử lý nhắc nhở',
      color: 'var(--p0)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--p0)" strokeWidth="2">
          <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      )
    },
    {
      label: 'Xe nâng / container',
      value: '2',
      sub: 'Hoạt động đúng quy định',
      color: 'var(--ok)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth="2">
          <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
          <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
        </svg>
      )
    },
    {
      label: 'Zone khu vực giám sát',
      value: String(zones.length),
      sub: 'Đang kích hoạt quy tắc',
      color: 'var(--cyan)',
      icon: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" strokeWidth="2">
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>
      )
    }
  ];

  // Detected objects displayed on the camera feed
  const detectedObjects = [
    {
      id: 'obj-moto',
      typeKey: 'xe máy',
      bx: '8.5%',
      by: '47.5%',
      bw: '7.5%',
      bh: '13%',
      color: '#f43f5e',
      fill: 'rgba(244,63,94,0.22)',
      label: 'XE MÁY · VI PHẠM ZONE'
    },
    {
      id: 'obj-car',
      typeKey: 'xe hơi',
      bx: '33.5%',
      by: '48%',
      bw: '9%',
      bh: '14%',
      color: '#f43f5e',
      fill: 'rgba(244,63,94,0.22)',
      label: 'XE HƠI TRẮNG · VI PHẠM'
    },
    {
      id: 'obj-fl',
      typeKey: 'xe nâng',
      bx: '21%',
      by: '38%',
      bw: '23%',
      bh: '42%',
      color: '#10b981',
      fill: 'rgba(16,185,129,0.12)',
      label: 'XE NÂNG RS01 · ĐƯỢC PHÉP'
    },
    {
      id: 'obj-cont',
      typeKey: 'container',
      bx: '55%',
      by: '56%',
      bw: '32%',
      bh: '32%',
      color: '#10b981',
      fill: 'rgba(16,185,129,0.09)',
      label: 'BÃI CONTAINER LẠNH'
    },
    {
      id: 'obj-ped',
      typeKey: 'người',
      bx: '50.2%',
      by: '39.5%',
      bw: '2.5%',
      bh: '7.5%',
      color: '#f43f5e',
      fill: 'rgba(244,63,94,0.22)',
      label: 'NGƯỜI ĐI BỘ · CẢNH BÁO'
    }
  ];

  const typeRules = [
    { label: 'Xe nâng', ok: true, icon: 'M5 18h9M5 18V8h5l2 4h4v6M18 18v-8' },
    { label: 'Xe container', ok: true, icon: 'M3 16V8h11v8M14 10h4l3 3v3M6 19a1.5 1.5 0 1 0 0-3M17 19a1.5 1.5 0 1 0 0-3' },
    { label: 'Xe hơi', ok: false, icon: 'M5 16l1-5 2-3h8l2 3 1 5M5 16h14M7 19a1.5 1.5 0 1 0 0-3M17 19a1.5 1.5 0 1 0 0-3' },
    { label: 'Xe máy', ok: false, icon: 'M5 17a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19 17a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8 14l3-5h4l3 5' },
    { label: 'Xe đạp', ok: false, icon: 'M5 17a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19 17a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8 14l3-6h5l2 6M12 8h3' }
  ];

  // Currently hovered event
  const currentHoveredEvent = events.find((e) => e.id === hoveredEventId) || null;

  // Filter events
  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (filterMode === 'violation' && e.ok) return false;
      if (filterMode === 'ok' && !e.ok) return false;

      if (searchFilter.trim()) {
        const q = searchFilter.toLowerCase().trim();
        return (
          e.obj.toLowerCase().includes(q) ||
          e.zone.toLowerCase().includes(q) ||
          e.time.includes(q)
        );
      }
      return true;
    });
  }, [events, filterMode, searchFilter]);

  // Robust zone match check
  const isZoneMatchingHover = (zone: PolygonZone) => {
    if (!currentHoveredEvent) return false;
    const evZone = currentHoveredEvent.zone.toLowerCase().trim();
    const zName = zone.name.toLowerCase().trim();

    if (evZone === zName) return true;
    if (evZone.includes(zName) || zName.includes(evZone)) return true;
    if (evZone.includes('cá nhân') && zName.includes('cá nhân')) return true;
    if (evZone.includes('bãi kiểm') && zName.includes('bãi kiểm')) return true;
    if (evZone.includes('di chuyển') && zName.includes('di chuyển')) return true;

    return false;
  };

  // Robust object match check
  const isObjectMatchingHover = (obj: typeof detectedObjects[0]) => {
    if (hoveredFeedObjectKey === obj.id) return true;
    if (!currentHoveredEvent) return false;

    const evObj = currentHoveredEvent.obj.toLowerCase().trim();
    const tk = obj.typeKey.toLowerCase().trim();

    if (evObj.includes(tk) || tk.includes(evObj)) return true;
    if (tk === 'xe nâng' && (evObj.includes('nâng') || evObj.includes('fl-'))) return true;
    if (tk === 'container' && (evObj.includes('container') || evObj.includes('15r') || evObj.includes('15h'))) return true;
    if (tk === 'xe máy' && evObj.includes('máy')) return true;
    if (tk === 'xe hơi' && (evObj.includes('hơi') || evObj.includes('trắng'))) return true;
    if (tk === 'người' && evObj.includes('người')) return true;

    return false;
  };

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
              justifyContent: 'space-between'
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

      {/* Main Grid: Feed + Rules (Left) & Area Events (Right) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.58fr) minmax(360px, 1fr)',
          gap: '18px',
          alignItems: 'start'
        }}
      >
        {/* Left: Feed & Type Rules */}
        <div>
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
            <img
              src="/assets/cam-baikiem.png"
              alt="Bãi kiểm camera feed"
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                objectFit: 'cover'
              }}
            />
            <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(5, 8, 12, 0.1)' }} />

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
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#ffffff' }}>BAI-KIEM · Bãi kiểm bốc dỡ</span>
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

            {/* SVG Polygon Zones for BAI-KIEM */}
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
                const isZoneMatched = isZoneMatchingHover(zone);

                return (
                  <polygon
                    key={zone.id}
                    points={pointsStr}
                    fill={`${zone.color}${isZoneMatched ? '50' : '16'}`}
                    stroke={isZoneMatched ? '#ffffff' : zone.color}
                    strokeWidth={isZoneMatched ? '3.2' : '1.6'}
                    strokeDasharray={isZoneMatched ? '0' : '6 4'}
                    vectorEffect="non-scaling-stroke"
                    style={{
                      transition: 'all 0.18s ease',
                      filter: isZoneMatched ? `drop-shadow(0 0 8px ${zone.color})` : 'none'
                    }}
                  />
                );
              })}
            </svg>

            {/* Zone Labels (centered) */}
            {zones.map((zone) => {
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
                    transform: isZoneMatched ? 'translate(-50%, -50%) scale(1.15)' : 'translate(-50%, -50%) scale(1)',
                    fontSize: '10px',
                    fontWeight: 700,
                    color: isZoneMatched ? '#000000' : '#ffffff',
                    backgroundColor: isZoneMatched ? '#ffffff' : `${zone.color}cc`,
                    padding: '3px 9px',
                    borderRadius: '5px',
                    backdropFilter: 'blur(4px)',
                    boxShadow: isZoneMatched
                      ? `0 0 18px rgba(255,255,255,0.9), 0 0 8px ${zone.color}`
                      : '0 2px 8px rgba(0,0,0,0.5)',
                    whiteSpace: 'nowrap',
                    pointerEvents: 'none',
                    letterSpacing: '0.04em',
                    transition: 'all 0.18s ease',
                    zIndex: 8
                  }}
                >
                  {zone.name.toUpperCase()}
                </span>
              );
            })}

            {/* Detected Objects with Bounding Boxes */}
            {detectedObjects.map((obj) => {
              const isHighlighted = isObjectMatchingHover(obj);

              return (
                <div
                  key={obj.id}
                  onMouseEnter={() => setHoveredFeedObjectKey(obj.id)}
                  onMouseLeave={() => setHoveredFeedObjectKey(null)}
                  style={{
                    position: 'absolute',
                    left: obj.bx,
                    top: obj.by,
                    width: obj.bw,
                    height: obj.bh,
                    border: `${isHighlighted ? '2.5px' : '1.8px'} solid ${isHighlighted ? '#ffffff' : obj.color}`,
                    backgroundColor: isHighlighted ? `${obj.color}45` : obj.fill,
                    boxShadow: isHighlighted
                      ? `0 0 24px ${obj.color}, 0 0 12px #ffffff`
                      : obj.color === '#f43f5e'
                      ? '0 0 12px rgba(244,63,94,0.4)'
                      : 'none',
                    borderRadius: '4px',
                    transform: isHighlighted ? 'scale(1.04)' : 'scale(1)',
                    transition: 'all 0.18s cubic-bezier(0.16, 1, 0.3, 1)',
                    cursor: 'pointer',
                    zIndex: isHighlighted ? 15 : 10
                  }}
                >
                  <span
                    style={{
                      position: 'absolute',
                      left: '-1px',
                      top: '-22px',
                      backgroundColor: isHighlighted ? '#ffffff' : obj.color,
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
                      transition: 'all 0.18s ease'
                    }}
                  >
                    {obj.label}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Type Rule Chips */}
          <div style={{ display: 'flex', gap: '8px', marginTop: '14px', flexWrap: 'wrap' }}>
            {typeRules.map((rule, idx) => (
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
                  color: rule.ok ? 'var(--ok)' : 'var(--p0)'
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
                <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--ink)' }}>Sự kiện khu vực</span>
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
                onClick={() => setFilterMode('violation')}
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  padding: '5px 12px',
                  borderRadius: '8px',
                  border: filterMode === 'violation' ? '1px solid var(--p0)' : '1px solid transparent',
                  cursor: 'pointer',
                  backgroundColor: filterMode === 'violation' ? 'var(--p0q)' : 'var(--raise)',
                  color: filterMode === 'violation' ? 'var(--p0)' : 'var(--ink2)'
                }}
              >
                ⚠ Vi phạm ({violationCount})
              </button>
              <button
                onClick={() => setFilterMode('ok')}
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  padding: '5px 12px',
                  borderRadius: '8px',
                  border: filterMode === 'ok' ? '1px solid var(--ok)' : '1px solid transparent',
                  cursor: 'pointer',
                  backgroundColor: filterMode === 'ok' ? 'var(--okq)' : 'var(--raise)',
                  color: filterMode === 'ok' ? 'var(--ok)' : 'var(--ink2)'
                }}
              >
                ✓ Được phép
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
                placeholder="Lọc nhanh đối tượng, zone..."
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

          {/* Events Stream List */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filteredEvents.length === 0 ? (
              <div style={{ padding: '32px 18px', textAlign: 'center', color: 'var(--ink3)', fontSize: '12.5px' }}>
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
                      gap: '14px',
                      padding: 'var(--event-py, 12px) var(--event-px, 18px)',
                      borderBottom: '1px solid var(--line)',
                      backgroundColor: isHovered ? 'var(--card-hover)' : 'transparent',
                      borderLeft: isHovered ? `3px solid ${isOk ? 'var(--ok)' : 'var(--p0)'}` : '3px solid transparent',
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
                      <div
                        style={{
                          fontSize: '13px',
                          fontWeight: 600,
                          color: isHovered ? (isOk ? 'var(--ok)' : 'var(--p0)') : 'var(--ink)'
                        }}
                      >
                        {event.obj}
                      </div>
                      <div style={{ fontSize: '11.5px', color: 'var(--ink3)', marginTop: '3px' }}>{event.zone}</div>
                    </div>

                    <span
                      style={{
                        fontSize: '10px',
                        fontWeight: 700,
                        padding: '3px 10px',
                        borderRadius: '20px',
                        backgroundColor: isOk ? 'var(--okq)' : 'var(--p0q)',
                        color: isOk ? 'var(--ok)' : 'var(--p0)',
                        border: `1px solid ${isOk ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`,
                        flex: 'none'
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
    </div>
  );
};
