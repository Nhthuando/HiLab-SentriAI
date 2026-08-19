import React, { useState, useMemo, useEffect, useCallback } from 'react';
import type { Vehicle } from '../../types';
import { getVehicles, updateVehicleStatus, registerVehicle } from '../../api/vehicles';

interface VehicleLabelTabProps {
  vehicles?: Vehicle[];
  labels?: Record<string, 'quen' | 'la'>;
  onToggleLabel?: (plate: string) => void;
}

type SortField = 'visits' | 'last' | 'plate' | null;
type SortDirection = 'asc' | 'desc';
type StatusFilter = 'all' | 'quen' | 'la';

export const VehicleLabelTab: React.FC<VehicleLabelTabProps> = ({
  vehicles: initialVehicles,
  labels: initialLabels,
  onToggleLabel: externalToggle,
}) => {
  const [vehicleList, setVehicleList] = useState<Vehicle[]>(initialVehicles || []);
  const [labelMap, setLabelMap] = useState<Record<string, 'quen' | 'la'>>(initialLabels || {});
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [sortField, setSortField] = useState<SortField>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // Register vehicle modal
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [newPlate, setNewPlate] = useState<string>('');
  const [newStatus, setNewStatus] = useState<'KNOWN' | 'STRANGER'>('KNOWN');
  const [newNote, setNewNote] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Fetch from real API
  const loadVehicles = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getVehicles();
      if (Array.isArray(data)) {
        setVehicleList(data);
        const map: Record<string, 'quen' | 'la'> = {};
        data.forEach((v) => {
          map[v.plate] = (v as any).status === 'STRANGER' ? 'la' : 'quen';
        });
        setLabelMap(map);
      }
    } catch (err: any) {
      console.warn('Failed to load vehicles from API, falling back to local state:', err);
      if (initialVehicles && initialVehicles.length > 0) {
        setVehicleList(initialVehicles);
      }
    } finally {
      setIsLoading(false);
    }
  }, [initialVehicles]);

  useEffect(() => {
    loadVehicles();
  }, [loadVehicles]);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 3500);
  };

  // Distinct vehicle types
  const uniqueTypes = useMemo(() => {
    const set = new Set<string>();
    vehicleList.forEach((v) => {
      if (v.type) set.add(v.type);
    });
    return Array.from(set);
  }, [vehicleList]);

  // Handle column header sort toggle
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      if (sortDirection === 'desc') {
        setSortDirection('asc');
      } else {
        setSortField(null);
        setSortDirection('desc');
      }
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  // Handle status toggle (optimistic update + API call)
  const handleToggle = async (plate: string) => {
    const currentStatus = labelMap[plate] || 'la';
    const nextStatus = currentStatus === 'quen' ? 'la' : 'quen';

    // Optimistic update
    setLabelMap((prev) => ({ ...prev, [plate]: nextStatus }));
    if (externalToggle) {
      externalToggle(plate);
    }

    try {
      await updateVehicleStatus(plate, nextStatus);
      showToast(`✓ Đã đổi trạng thái biển số ${plate} thành ${nextStatus === 'quen' ? 'Xe quen' : 'Xe lạ'}`);
    } catch (err: any) {
      // Rollback on error
      setLabelMap((prev) => ({ ...prev, [plate]: currentStatus }));
      showToast(`⚠ Lỗi khi cập nhật trạng thái: ${err.message || 'Không kết nối được server'}`);
    }
  };

  // Handle create new vehicle
  const handleCreateVehicle = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPlate.trim()) return;

    setIsSubmitting(true);
    try {
      await registerVehicle({
        plateNumber: newPlate.trim().toUpperCase(),
        status: newStatus,
        note: newNote.trim() || undefined,
      });
      showToast(`✓ Đăng ký thành công biển số ${newPlate.trim().toUpperCase()}`);
      setIsAddModalOpen(false);
      setNewPlate('');
      setNewNote('');
      await loadVehicles();
    } catch (err: any) {
      showToast(`⚠ ${err.message || 'Không thể đăng ký biển số'}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Filter and sort vehicles
  const filteredVehicles = useMemo(() => {
    let result = [...vehicleList];

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
      result = result.filter((v) => (labelMap[v.plate] || 'la') === statusFilter);
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
          return sortDirection === 'desc' ? b.last.localeCompare(a.last) : a.last.localeCompare(b.last);
        }
        if (sortField === 'plate') {
          return sortDirection === 'desc' ? b.plate.localeCompare(a.plate) : a.plate.localeCompare(b.plate);
        }
        return 0;
      });
    }

    return result;
  }, [vehicleList, labelMap, searchQuery, statusFilter, typeFilter, sortField, sortDirection]);

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
        boxShadow: 'var(--shadow-lg)',
        position: 'relative',
      }}
    >
      {/* Toast Notification */}
      {toastMsg && (
        <div
          className="glass-panel animate-msg"
          style={{
            position: 'absolute',
            top: '16px',
            right: '20px',
            zIndex: 50,
            padding: '10px 18px',
            borderRadius: '10px',
            backgroundColor: toastMsg.startsWith('✓') ? 'var(--okq)' : 'var(--p0q)',
            border: `1px solid ${toastMsg.startsWith('✓') ? 'var(--ok)' : 'var(--p0)'}`,
            color: toastMsg.startsWith('✓') ? 'var(--ok)' : 'var(--p0)',
            fontSize: '12.5px',
            fontWeight: 600,
            boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
          }}
        >
          {toastMsg}
        </div>
      )}

      {/* Header with Title & Description & Add Button */}
      <div
        style={{
          padding: '16px 22px',
          borderBottom: '1px solid var(--line)',
          backgroundColor: 'var(--panel)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <div>
          <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--ink)' }}>
            Gắn nhãn phương tiện thu thập
          </div>
          <div style={{ fontSize: '12px', color: 'var(--ink2)', marginTop: '3px' }}>
            Đánh dấu xe quen (hợp lệ) / xe lạ (cảnh báo) — Hệ thống tự động phân loại và phát hiện khi xe đi vào cổng hoặc zone.
          </div>
        </div>

        <button
          onClick={() => setIsAddModalOpen(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 14px',
            borderRadius: '8px',
            border: 'none',
            backgroundColor: 'var(--acc)',
            color: '#ffffff',
            fontSize: '12.5px',
            fontWeight: 600,
            cursor: 'pointer',
            boxShadow: '0 2px 8px var(--acc-glow)',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>Đăng ký biển số mới</span>
        </button>
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
          flexWrap: 'wrap',
        }}
      >
        {/* Search Input */}
        <div
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            minWidth: '240px',
            flex: '1 1 240px',
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
              outline: 'none',
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
                padding: '2px',
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
              gap: '2px',
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
                color: statusFilter === 'all' ? '#fff' : 'var(--ink2)',
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
                color: statusFilter === 'quen' ? 'var(--ok)' : 'var(--ink2)',
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
                color: statusFilter === 'la' ? 'var(--p0)' : 'var(--ink2)',
              }}
            >
              ⚠ Xe lạ
            </button>
          </div>
        </div>

        {/* Filter by Vehicle Type */}
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
              cursor: 'pointer',
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

        {/* Result Counter & Refresh */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontSize: '11.5px',
              color: 'var(--ink3)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {filteredVehicles.length} / {vehicleList.length} xe
          </span>

          <button
            onClick={() => loadVehicles()}
            title="Làm mới danh sách từ server"
            style={{
              background: 'transparent',
              border: '1px solid var(--line2)',
              borderRadius: '7px',
              padding: '4px 8px',
              color: 'var(--ink2)',
              cursor: 'pointer',
              fontSize: '11px',
            }}
          >
            ↻
          </button>
        </div>
      </div>

      {/* Table Header with Sort Arrows */}
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
          letterSpacing: '0.04em',
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
            color: sortField === 'plate' ? 'var(--acc)' : 'inherit',
          }}
          title="Bấm để sắp xếp theo biển số"
        >
          <span>Biển số xe</span>
          {renderSortIndicator('plate')}
        </div>

        {/* Column 3: Loại phương tiện */}
        <div>Loại phương tiện</div>

        {/* Column 4: Lượt vào (Sortable) */}
        <div
          onClick={() => handleSort('visits')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            cursor: 'pointer',
            userSelect: 'none',
            color: sortField === 'visits' ? 'var(--acc)' : 'inherit',
          }}
          title="Bấm để sắp xếp theo số lượt vào"
        >
          <span>Lượt vào</span>
          {renderSortIndicator('visits')}
        </div>

        {/* Column 5: Lần cuối ghi nhận (Sortable) */}
        <div
          onClick={() => handleSort('last')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            cursor: 'pointer',
            userSelect: 'none',
            color: sortField === 'last' ? 'var(--acc)' : 'inherit',
          }}
          title="Bấm để sắp xếp theo thời gian mới/cũ nhất"
        >
          <span>Lần cuối ghi nhận</span>
          {renderSortIndicator('last')}
        </div>

        {/* Column 6: Nhãn phân loại */}
        <div>Nhãn phân loại</div>
      </div>

      {/* Table Rows or Loading Skeleton */}
      <div>
        {isLoading && vehicleList.length === 0 ? (
          <div style={{ padding: '36px 20px', textAlign: 'center', color: 'var(--ink3)' }}>
            <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--acc)' }}>
              Đang tải danh sách phương tiện từ máy chủ...
            </div>
          </div>
        ) : filteredVehicles.length === 0 ? (
          <div style={{ padding: '40px 18px', textAlign: 'center', color: 'var(--ink3)' }}>
            <div style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--ink2)', marginBottom: '4px' }}>
              Chưa có xe nào được ghi nhận
            </div>
            <div style={{ fontSize: '12px' }}>
              Thử thay đổi từ khóa tìm kiếm hoặc bấm "Đăng ký biển số mới".
            </div>
          </div>
        ) : (
          filteredVehicles.map((v) => {
            const isStranger = (labelMap[v.plate] || 'la') === 'la';
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
                  transition: 'background-color 0.15s ease',
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
                      background: `linear-gradient(150deg, ${v.tint || (isStranger ? '#f43f5e' : '#10b981')}, #0d1017)`,
                      border: '1px solid var(--line2)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'rgba(255,255,255,0.6)',
                      fontSize: '9px',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
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
                      letterSpacing: '0.02em',
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
                      borderRadius: '6px',
                    }}
                  >
                    {v.visits} lượt
                  </span>
                </div>

                <div
                  style={{
                    color: sortField === 'last' ? 'var(--acc)' : 'var(--ink3)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                  }}
                >
                  {v.last}
                </div>

                <div>
                  <button
                    onClick={() => handleToggle(v.plate)}
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
                      boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
                    }}
                  >
                    <span
                      style={{
                        width: '7px',
                        height: '7px',
                        borderRadius: '50%',
                        backgroundColor: tagColor,
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

      {/* Modal: Đăng ký biển số mới */}
      {isAddModalOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.65)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
            padding: '20px',
          }}
          onClick={() => setIsAddModalOpen(false)}
        >
          <div
            className="glass-panel animate-modal"
            style={{
              width: '100%',
              maxWidth: '420px',
              borderRadius: '16px',
              backgroundColor: 'var(--card)',
              border: '1px solid var(--line2)',
              boxShadow: 'var(--shadow-lg)',
              overflow: 'hidden',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--line)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                backgroundColor: 'var(--panel)',
              }}
            >
              <div style={{ fontSize: '14.5px', fontWeight: 700, color: 'var(--ink)' }}>
                Đăng ký biển số xe mới
              </div>
              <button
                onClick={() => setIsAddModalOpen(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--ink3)',
                  fontSize: '16px',
                  cursor: 'pointer',
                  padding: '4px',
                }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateVehicle} style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink2)', display: 'block', marginBottom: '6px' }}>
                  Biển số xe (vd: 29A-123.45, 15C-888.99):
                </label>
                <input
                  value={newPlate}
                  onChange={(e) => setNewPlate(e.target.value.toUpperCase())}
                  placeholder="29A-123.45"
                  autoFocus
                  required
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    borderRadius: '9px',
                    border: '1px solid var(--line2)',
                    backgroundColor: 'var(--bg)',
                    color: 'var(--ink)',
                    fontSize: '13px',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                    outline: 'none',
                  }}
                />
              </div>

              <div>
                <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink2)', display: 'block', marginBottom: '6px' }}>
                  Trạng thái đăng ký:
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                  <button
                    type="button"
                    onClick={() => setNewStatus('KNOWN')}
                    style={{
                      padding: '8px',
                      borderRadius: '8px',
                      border: newStatus === 'KNOWN' ? '2px solid var(--ok)' : '1px solid var(--line2)',
                      backgroundColor: newStatus === 'KNOWN' ? 'var(--okq)' : 'var(--raise)',
                      color: newStatus === 'KNOWN' ? 'var(--ok)' : 'var(--ink2)',
                      fontWeight: 700,
                      fontSize: '12px',
                      cursor: 'pointer',
                    }}
                  >
                    ✓ Xe quen (Hợp lệ)
                  </button>
                  <button
                    type="button"
                    onClick={() => setNewStatus('STRANGER')}
                    style={{
                      padding: '8px',
                      borderRadius: '8px',
                      border: newStatus === 'STRANGER' ? '2px solid var(--p0)' : '1px solid var(--line2)',
                      backgroundColor: newStatus === 'STRANGER' ? 'var(--p0q)' : 'var(--raise)',
                      color: newStatus === 'STRANGER' ? 'var(--p0)' : 'var(--ink2)',
                      fontWeight: 700,
                      fontSize: '12px',
                      cursor: 'pointer',
                    }}
                  >
                    ⚠ Xe lạ (Cảnh báo)
                  </button>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink2)', display: 'block', marginBottom: '6px' }}>
                  Ghi chú thêm:
                </label>
                <input
                  value={newNote}
                  onChange={(e) => setNewNote(e.target.value)}
                  placeholder="vd: Xe giám đốc, xe nhà thầu thi công..."
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    border: '1px solid var(--line2)',
                    backgroundColor: 'var(--bg)',
                    color: 'var(--ink)',
                    fontSize: '12px',
                    outline: 'none',
                  }}
                />
              </div>

              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'flex-end',
                  gap: '10px',
                  marginTop: '10px',
                }}
              >
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '8px',
                    border: '1px solid var(--line2)',
                    backgroundColor: 'transparent',
                    color: 'var(--ink2)',
                    fontSize: '12.5px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting || !newPlate.trim()}
                  style={{
                    padding: '8px 20px',
                    borderRadius: '8px',
                    border: 'none',
                    backgroundColor: newPlate.trim() ? 'var(--acc)' : 'var(--raise)',
                    color: newPlate.trim() ? '#ffffff' : 'var(--ink3)',
                    fontSize: '12.5px',
                    fontWeight: 700,
                    cursor: newPlate.trim() ? 'pointer' : 'not-allowed',
                    boxShadow: newPlate.trim() ? '0 2px 8px var(--acc-glow)' : 'none',
                  }}
                >
                  {isSubmitting ? 'Đang lưu...' : 'Thêm phương tiện'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
