import React, { useState, useMemo } from 'react';
import type { Vehicle } from '../../types';

interface VehicleLabelTabProps {
  vehicles: Vehicle[];
  labels: Record<string, 'quen' | 'la'>;
  onToggleLabel: (plate: string) => void;
}

type SortOrder = 'default' | 'desc' | 'asc';
type StatusFilter = 'all' | 'quen' | 'la';

export const VehicleLabelTab: React.FC<VehicleLabelTabProps> = ({ vehicles, labels, onToggleLabel }) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [sortOrder, setSortOrder] = useState<SortOrder>('default');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  // Filter and sort vehicles
  const filteredVehicles = useMemo(() => {
    let result = [...vehicles];

    // 1. Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter(
        (v) =>
          v.plate.toLowerCase().includes(q) ||
          v.type.toLowerCase().includes(q) ||
          v.last.toLowerCase().includes(q)
      );
    }

    // 2. Status filter
    if (statusFilter !== 'all') {
      result = result.filter((v) => labels[v.plate] === statusFilter);
    }

    // 3. Sort by visits (Lượt vào)
    if (sortOrder === 'desc') {
      result.sort((a, b) => b.visits - a.visits);
    } else if (sortOrder === 'asc') {
      result.sort((a, b) => a.visits - b.visits);
    }

    return result;
  }, [vehicles, labels, searchQuery, statusFilter, sortOrder]);

  return (
    <div
      className="glass-panel"
      style={{
        borderRadius: '16px',
        overflow: 'hidden',
        boxShadow: 'var(--shadow-lg)'
      }}
    >
      {/* Header with Title & Description */}
      <div style={{ padding: '16px 22px', borderBottom: '1px solid var(--line)', backgroundColor: 'rgba(26, 30, 39, 0.6)' }}>
        <div style={{ fontSize: '15px', fontWeight: 700, color: '#ffffff' }}>
          Gắn nhãn phương tiện thu thập
        </div>
        <div style={{ fontSize: '12px', color: 'var(--ink2)', marginTop: '3px' }}>
          Đánh dấu xe quen (hợp lệ) / xe lạ (cảnh báo) — Hệ thống tự động phân loại và phát hiện khi xe đi vào zone.
        </div>
      </div>

      {/* Filter & Search Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '14px',
          padding: '14px 22px',
          backgroundColor: 'rgba(15, 18, 23, 0.6)',
          borderBottom: '1px solid var(--line)',
          flexWrap: 'wrap'
        }}
      >
        {/* Search Input */}
        <div
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            minWidth: '260px',
            flex: '1 1 260px'
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--ink3)"
            strokeWidth="2"
            style={{ position: 'absolute', left: '12px', pointerEvents: 'none' }}
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Tìm theo biển số, loại xe, thời gian…"
            style={{
              width: '100%',
              backgroundColor: 'var(--bg)',
              border: '1px solid var(--line2)',
              borderRadius: '10px',
              padding: '8px 32px 8px 34px',
              fontSize: '12.5px',
              color: 'var(--ink)',
              outline: 'none'
            }}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              style={{
                position: 'absolute',
                right: '10px',
                background: 'transparent',
                border: 'none',
                color: 'var(--ink3)',
                cursor: 'pointer',
                fontSize: '12px',
                padding: '2px'
              }}
            >
              ✕
            </button>
          )}
        </div>

        {/* Sort by Visits */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11.5px', color: 'var(--ink3)', fontWeight: 600 }}>Lượt vào:</span>
          <div
            style={{
              display: 'flex',
              backgroundColor: 'var(--bg)',
              border: '1px solid var(--line2)',
              borderRadius: '9px',
              padding: '3px',
              gap: '2px'
            }}
          >
            <button
              onClick={() => setSortOrder('default')}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '5px 10px',
                borderRadius: '7px',
                border: 'none',
                cursor: 'pointer',
                backgroundColor: sortOrder === 'default' ? 'var(--acc)' : 'transparent',
                color: sortOrder === 'default' ? '#fff' : 'var(--ink2)'
              }}
            >
              Mặc định
            </button>
            <button
              onClick={() => setSortOrder('desc')}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '5px 10px',
                borderRadius: '7px',
                border: 'none',
                cursor: 'pointer',
                backgroundColor: sortOrder === 'desc' ? 'var(--acc)' : 'transparent',
                color: sortOrder === 'desc' ? '#fff' : 'var(--ink2)'
              }}
            >
              Giảm dần ↓
            </button>
            <button
              onClick={() => setSortOrder('asc')}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '5px 10px',
                borderRadius: '7px',
                border: 'none',
                cursor: 'pointer',
                backgroundColor: sortOrder === 'asc' ? 'var(--acc)' : 'transparent',
                color: sortOrder === 'asc' ? '#fff' : 'var(--ink2)'
              }}
            >
              Tăng dần ↑
            </button>
          </div>
        </div>

        {/* Filter by Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11.5px', color: 'var(--ink3)', fontWeight: 600 }}>Trạng thái:</span>
          <div
            style={{
              display: 'flex',
              backgroundColor: 'var(--bg)',
              border: '1px solid var(--line2)',
              borderRadius: '9px',
              padding: '3px',
              gap: '2px'
            }}
          >
            <button
              onClick={() => setStatusFilter('all')}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '5px 10px',
                borderRadius: '7px',
                border: 'none',
                cursor: 'pointer',
                backgroundColor: statusFilter === 'all' ? 'var(--acc)' : 'transparent',
                color: statusFilter === 'all' ? '#fff' : 'var(--ink2)'
              }}
            >
              Tất cả
            </button>
            <button
              onClick={() => setStatusFilter('quen')}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '5px 10px',
                borderRadius: '7px',
                border: 'none',
                cursor: 'pointer',
                backgroundColor: statusFilter === 'quen' ? 'var(--okq)' : 'transparent',
                color: statusFilter === 'quen' ? 'var(--ok)' : 'var(--ink2)'
              }}
            >
              ✓ Xe quen
            </button>
            <button
              onClick={() => setStatusFilter('la')}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '5px 10px',
                borderRadius: '7px',
                border: 'none',
                cursor: 'pointer',
                backgroundColor: statusFilter === 'la' ? 'var(--p0q)' : 'transparent',
                color: statusFilter === 'la' ? 'var(--p0)' : 'var(--ink2)'
              }}
            >
              ⚠ Xe lạ
            </button>
          </div>
        </div>

        <div style={{ flex: 1 }} />

        {/* Result Counter */}
        <span
          style={{
            fontSize: '11.5px',
            color: 'var(--ink3)',
            fontFamily: 'var(--font-mono)'
          }}
        >
          {filteredVehicles.length} / {vehicles.length} xe
        </span>
      </div>

      {/* Table Header */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '70px 1.3fr 1fr 0.8fr 0.9fr 140px',
          padding: '12px 22px',
          borderBottom: '1px solid var(--line)',
          fontSize: '11.5px',
          color: 'var(--ink3)',
          fontWeight: 700,
          backgroundColor: 'rgba(20, 23, 31, 0.4)',
          letterSpacing: '0.04em'
        }}
      >
        <div>Ảnh</div>
        <div>Biển số xe</div>
        <div>Loại phương tiện</div>
        <div>Lượt vào</div>
        <div>Lần cuối ghi nhận</div>
        <div>Nhãn phân loại</div>
      </div>

      {/* Table Rows */}
      <div>
        {filteredVehicles.length === 0 ? (
          <div style={{ padding: '40px 18px', textAlign: 'center', color: 'var(--ink3)' }}>
            <div style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--ink2)', marginBottom: '4px' }}>
              Không tìm thấy phương tiện nào
            </div>
            <div style={{ fontSize: '12px' }}>
              Thử thay đổi từ khóa tìm kiếm hoặc bỏ bộ lọc trạng thái.
            </div>
          </div>
        ) : (
          filteredVehicles.map((v) => {
            const isStranger = labels[v.plate] === 'la';
            const tagLabel = isStranger ? 'Xe lạ (Cảnh báo)' : 'Xe quen (Hợp lệ)';
            const tagColor = isStranger ? 'var(--p0)' : 'var(--ok)';
            const tagBg = isStranger ? 'var(--p0q)' : 'var(--okq)';

            return (
              <div
                key={v.plate}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '70px 1.3fr 1fr 0.8fr 0.9fr 140px',
                  padding: '12px 22px',
                  borderBottom: '1px solid var(--line)',
                  alignItems: 'center',
                  fontSize: '13px',
                  transition: 'background-color 0.15s ease'
                }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--card-hover)')}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
              >
                <div>
                  <div
                    style={{
                      width: '54px',
                      height: '34px',
                      borderRadius: '7px',
                      background: `linear-gradient(150deg, ${v.tint}, #0d1017)`,
                      border: '1px solid var(--line2)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'rgba(255,255,255,0.4)',
                      fontSize: '9px',
                      fontFamily: 'var(--font-mono)'
                    }}
                  >
                    CROP
                  </div>
                </div>

                <div>
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
                      fontSize: '13.5px',
                      color: '#ffffff',
                      letterSpacing: '0.02em'
                    }}
                  >
                    {v.plate}
                  </span>
                </div>

                <div style={{ color: 'var(--ink2)' }}>{v.type}</div>

                <div>
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 600,
                      fontSize: '12px',
                      color: 'var(--ink)',
                      backgroundColor: 'var(--raise)',
                      padding: '2px 8px',
                      borderRadius: '6px'
                    }}
                  >
                    {v.visits} lượt
                  </span>
                </div>

                <div
                  style={{
                    color: 'var(--ink3)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px'
                  }}
                >
                  {v.last}
                </div>

                <div>
                  <button
                    onClick={() => onToggleLabel(v.plate)}
                    title={`Bấm để chuyển thành ${isStranger ? 'Xe quen' : 'Xe lạ'}`}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '7px',
                      fontSize: '11.5px',
                      fontWeight: 700,
                      padding: '6px 14px',
                      borderRadius: '20px',
                      border: `1px solid ${tagColor}`,
                      backgroundColor: tagBg,
                      color: tagColor,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                      boxShadow: '0 1px 4px rgba(0,0,0,0.2)'
                    }}
                  >
                    <span
                      style={{
                        width: '7px',
                        height: '7px',
                        borderRadius: '50%',
                        backgroundColor: tagColor
                      }}
                    />
                    <span>{tagLabel}</span>
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
