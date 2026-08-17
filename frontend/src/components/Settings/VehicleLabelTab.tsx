import React, { useState, useMemo } from 'react';
import type { Vehicle } from '../../types';

interface VehicleLabelTabProps {
  vehicles: Vehicle[];
  labels: Record<string, 'quen' | 'la'>;
  onToggleLabel: (plate: string) => void;
}

type SortField = 'visits' | 'last' | 'plate' | null;
type SortDirection = 'asc' | 'desc';
type StatusFilter = 'all' | 'quen' | 'la';

export const VehicleLabelTab: React.FC<VehicleLabelTabProps> = ({ vehicles, labels, onToggleLabel }) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [sortField, setSortField] = useState<SortField>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // Distinct vehicle types
  const uniqueTypes = useMemo(() => {
    const set = new Set<string>();
    vehicles.forEach((v) => {
      if (v.type) set.add(v.type);
    });
    return Array.from(set);
  }, [vehicles]);

  // Handle column header sort toggle
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      if (sortDirection === 'desc') {
        setSortDirection('asc');
      } else {
        // Reset sort
        setSortField(null);
        setSortDirection('desc');
      }
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

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

    // 3. Vehicle type filter
    if (typeFilter !== 'all') {
      result = result.filter((v) => v.type === typeFilter);
    }

    // 4. Column Header Sorting
    if (sortField) {
      result.sort((a, b) => {
        if (sortField === 'visits') {
          return sortDirection === 'desc' ? b.visits - a.visits : a.visits - b.visits;
        }
        if (sortField === 'last') {
          // Compare formatted timestamp '16/08 09:18'
          return sortDirection === 'desc'
            ? b.last.localeCompare(a.last)
            : a.last.localeCompare(b.last);
        }
        if (sortField === 'plate') {
          return sortDirection === 'desc'
            ? b.plate.localeCompare(a.plate)
            : a.plate.localeCompare(b.plate);
        }
        return 0;
      });
    }

    return result;
  }, [vehicles, labels, searchQuery, statusFilter, typeFilter, sortField, sortDirection]);

  // Render sort arrow indicator
  const renderSortIndicator = (field: SortField) => {
    const isActive = sortField === field;
    if (!isActive) {
      return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--ink3)" strokeWidth="2" style={{ opacity: 0.5 }}>
          <path d="m7 15 5 5 5-5M7 9l5-5 5 5" />
        </svg>
      );
    }
    if (sortDirection === 'desc') {
      return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--acc)" strokeWidth="2.4">
          <path d="M12 5v14M19 12l-7 7-7-7" />
        </svg>
      );
    }
    return (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--acc)" strokeWidth="2.4">
        <path d="M12 19V5M5 12l7-7 7 7" />
      </svg>
    );
  };

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
      <div style={{ padding: '16px 22px', borderBottom: '1px solid var(--line)', backgroundColor: 'var(--panel)' }}>
        <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--ink)' }}>
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
          backgroundColor: 'var(--bg-subtle)',
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
            minWidth: '240px',
            flex: '1 1 240px'
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

        {/* Filter by Status (Xe quen / Xe lạ) */}
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
                padding: '5px 11px',
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
                padding: '5px 11px',
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
                padding: '5px 11px',
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

        {/* Filter by Vehicle Type (Container, Xe tải, Xe con...) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11.5px', color: 'var(--ink3)', fontWeight: 600 }}>Loại xe:</span>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            style={{
              backgroundColor: 'var(--bg)',
              border: '1px solid var(--line2)',
              borderRadius: '9px',
              padding: '6px 12px',
              fontSize: '12px',
              color: typeFilter === 'all' ? 'var(--ink2)' : 'var(--ink)',
              fontWeight: 600,
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            <option value="all">Tất cả loại xe ({uniqueTypes.length})</option>
            {uniqueTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
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

      {/* Table Header with Sort Arrows on the right of Titles */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '70px 1.3fr 1fr 1fr 1fr 140px',
          padding: 'var(--table-py, 12px) var(--table-px, 22px)',
          borderBottom: '1px solid var(--line)',
          fontSize: '11.5px',
          color: 'var(--ink3)',
          fontWeight: 700,
          backgroundColor: 'var(--raise)',
          letterSpacing: '0.04em'
        }}
      >
        <div>Ảnh</div>

        {/* Column 2: Biển số xe (Sortable) */}
        <div
          onClick={() => handleSort('plate')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            cursor: 'pointer',
            userSelect: 'none',
            color: sortField === 'plate' ? 'var(--acc)' : 'inherit'
          }}
          title="Bấm để sắp xếp theo biển số"
        >
          <span>Biển số xe</span>
          {renderSortIndicator('plate')}
        </div>

        {/* Column 3: Loại phương tiện */}
        <div>Loại phương tiện</div>

        {/* Column 4: Lượt vào (Sortable with arrow on right of title) */}
        <div
          onClick={() => handleSort('visits')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            cursor: 'pointer',
            userSelect: 'none',
            color: sortField === 'visits' ? 'var(--acc)' : 'inherit'
          }}
          title="Bấm để sắp xếp theo số lượt vào"
        >
          <span>Lượt vào</span>
          {renderSortIndicator('visits')}
        </div>

        {/* Column 5: Lần cuối ghi nhận (Sortable with arrow on right of title) */}
        <div
          onClick={() => handleSort('last')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            cursor: 'pointer',
            userSelect: 'none',
            color: sortField === 'last' ? 'var(--acc)' : 'inherit'
          }}
          title="Bấm để sắp xếp theo thời gian mới/cũ nhất"
        >
          <span>Lần cuối ghi nhận</span>
          {renderSortIndicator('last')}
        </div>

        {/* Column 6: Nhãn phân loại */}
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
              Thử thay đổi từ khóa tìm kiếm hoặc bỏ bớt bộ lọc.
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
                  gridTemplateColumns: '70px 1.3fr 1fr 1fr 1fr 140px',
                  padding: 'var(--table-py, 12px) var(--table-px, 22px)',
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
                      color: 'var(--ink)',
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
                      color: sortField === 'visits' ? 'var(--acc)' : 'var(--ink)',
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
                    color: sortField === 'last' ? 'var(--acc)' : 'var(--ink3)',
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
