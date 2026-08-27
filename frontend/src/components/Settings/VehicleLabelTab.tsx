import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, Trash2 } from 'lucide-react';
import type { Vehicle } from '../../types';
import {
  deleteVehicles,
  getVehicles,
  registerVehicle,
  resetDemoData,
  updateVehicleStatus,
} from '../../api/vehicles';
import { getCameraConfig, updateCameraConfig } from '../../api/cameras';
import { getCropImageUrl } from '../../api/events';

interface VehicleLabelTabProps {
  vehicles?: Vehicle[];
  labels?: Record<string, 'quen' | 'la'>;
  onToggleLabel?: (plate: string) => void;
}

type SortField = 'visits' | 'last' | 'plate' | null;
type SortDirection = 'asc' | 'desc';
type StatusFilter = 'all' | 'quen' | 'la';
type ToastTone = 'success' | 'danger';
const VEHICLES_PER_PAGE = 10;

export const VehicleLabelTab: React.FC<VehicleLabelTabProps> = ({
  vehicles: initialVehicles,
  labels: initialLabels,
  onToggleLabel: externalToggle,
}) => {
  const [vehicleList, setVehicleList] = useState<Vehicle[]>(initialVehicles || []);
  const [labelMap, setLabelMap] = useState<Record<string, 'quen' | 'la'>>(initialLabels || {});
  const [filterLabelMap, setFilterLabelMap] = useState<Record<string, 'quen' | 'la'>>(initialLabels || {});
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [toast, setToast] = useState<{ message: string; tone: ToastTone } | null>(null);
  const toastTimerRef = useRef<number | null>(null);

  // Confidence Threshold for Gate Event Logging
  const [minConfidence, setMinConfidence] = useState<number>(70);
  const [isSavingConfig, setIsSavingConfig] = useState<boolean>(false);

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [sortField, setSortField] = useState<SortField>('last');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // Register vehicle modal
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [newPlate, setNewPlate] = useState<string>('');
  const [newStatus, setNewStatus] = useState<'KNOWN' | 'STRANGER'>('KNOWN');
  const [newNote, setNewNote] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [selectedCrop, setSelectedCrop] = useState<{ plate: string; url: string } | null>(null);
  const [selectedPlates, setSelectedPlates] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);
  const [pendingDeletePlates, setPendingDeletePlates] = useState<string[] | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  // Fetch from real API
  const loadVehicles = useCallback(async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const data = await getVehicles({ limit: 200 });
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
      if (!silent) setIsLoading(false);
    }
  }, [initialVehicles]);

  useEffect(() => {
    void loadVehicles();
    const vehicleTimer = window.setInterval(() => void loadVehicles(true), 5000);
    // Load camera GATE-01 confidence configuration
    getCameraConfig('GATE-01')
      .then((cfg) => {
        if (cfg && cfg.minConfidence !== undefined) {
          setMinConfidence(Math.round(cfg.minConfidence * 100));
        }
      })
      .catch((err) => {
        console.warn('Could not load camera config from API:', err);
      });
    return () => window.clearInterval(vehicleTimer);
  }, [loadVehicles]);

  const handleSaveConfidence = async (val?: number) => {
    const valueToSave = val !== undefined ? val : minConfidence;
    setIsSavingConfig(true);
    try {
      await updateCameraConfig('GATE-01', { minConfidence: valueToSave / 100.0 });
      showToast(`✓ Đã lưu ngưỡng độ chính xác nhận diện: ${valueToSave}%`);
    } catch (err) {
      console.error('Failed to update confidence config:', err);
      showToast('Lỗi khi lưu cấu hình độ chính xác!', 'danger');
    } finally {
      setIsSavingConfig(false);
    }
  };

  const showToast = (message: string, tone: ToastTone = 'success') => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    setToast({ message, tone });
    toastTimerRef.current = window.setTimeout(() => {
      setToast(null);
      toastTimerRef.current = null;
    }, 3500);
  };

  useEffect(() => () => {
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
  }, []);

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
      showToast(
        `Đã chuyển biển số ${plate} thành ${nextStatus === 'quen' ? 'Xe quen' : 'Xe lạ'}`,
        nextStatus === 'quen' ? 'success' : 'danger',
      );
    } catch (err: any) {
      // Rollback on error
      setLabelMap((prev) => ({ ...prev, [plate]: currentStatus }));
      showToast(`Lỗi khi cập nhật trạng thái: ${err.message || 'Không kết nối được server'}`, 'danger');
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
      showToast(err.message || 'Không thể đăng ký biển số', 'danger');
    } finally {
      setIsSubmitting(false);
    }
  };

  const requestDelete = (plates: string[]) => {
    const uniquePlates = Array.from(new Set(plates.filter(Boolean)));
    if (uniquePlates.length > 0) setPendingDeletePlates(uniquePlates);
  };

  const handleConfirmDelete = async () => {
    const plates = pendingDeletePlates || [];
    if (plates.length === 0) return;
    setIsDeleting(true);
    try {
      await deleteVehicles(plates);
      setVehicleList((current) => current.filter((vehicle) => !plates.includes(vehicle.plate)));
      setLabelMap((current) => {
        const next = { ...current };
        plates.forEach((plate) => delete next[plate]);
        return next;
      });
      setSelectedPlates(new Set());
      setPendingDeletePlates(null);
      const listedPlates = plates.slice(0, 3).join(', ');
      const remainingCount = Math.max(0, plates.length - 3);
      showToast(
        `Đã xóa biển số ${listedPlates}${remainingCount > 0 ? `,...+${remainingCount}` : ''}`,
        'danger',
      );
    } catch (err: any) {
      showToast(err.message || 'Không thể xóa biển số đã chọn', 'danger');
    } finally {
      setIsDeleting(false);
    }
  };

  const handleResetDemo = async () => {
    if (!window.confirm('Xóa toàn bộ nhật ký nhận diện và danh sách gắn nhãn của phiên demo local?')) return;
    setIsDeleting(true);
    try {
      await resetDemoData();
      setVehicleList([]);
      setLabelMap({});
      setSelectedPlates(new Set());
      showToast('✓ Đã đặt lại dữ liệu demo');
      window.setTimeout(() => window.location.reload(), 500);
    } catch (err: any) {
      showToast(err.message || 'Không thể đặt lại dữ liệu demo', 'danger');
    } finally {
      setIsDeleting(false);
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
          v.last.toLowerCase().includes(q)
      );
    }

    // 2. Status filter
    if (statusFilter !== 'all') {
      result = result.filter((v) => (filterLabelMap[v.plate] || 'la') === statusFilter);
    }

    // 3. Column Header Sorting
    if (sortField) {
      result.sort((a, b) => {
        if (sortField === 'visits') {
          return sortDirection === 'desc' ? b.visits - a.visits : a.visits - b.visits;
        }
        if (sortField === 'last') {
          const aTime = a.lastSeenAt ? Date.parse(a.lastSeenAt) : 0;
          const bTime = b.lastSeenAt ? Date.parse(b.lastSeenAt) : 0;
          return sortDirection === 'desc' ? bTime - aTime : aTime - bTime;
        }
        if (sortField === 'plate') {
          return sortDirection === 'desc' ? b.plate.localeCompare(a.plate) : a.plate.localeCompare(b.plate);
        }
        return 0;
      });
    }

    return result;
  }, [vehicleList, filterLabelMap, searchQuery, statusFilter, sortField, sortDirection]);

  const pageCount = Math.max(1, Math.ceil(filteredVehicles.length / VEHICLES_PER_PAGE));
  const paginatedVehicles = useMemo(() => {
    const start = (currentPage - 1) * VEHICLES_PER_PAGE;
    return filteredVehicles.slice(start, start + VEHICLES_PER_PAGE);
  }, [currentPage, filteredVehicles]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, pageCount));
  }, [pageCount]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, statusFilter, sortField, sortDirection]);

  const changeStatusFilter = (nextFilter: StatusFilter) => {
    setFilterLabelMap({ ...labelMap });
    setStatusFilter(nextFilter);
  };

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
      {toast && createPortal((
        <div
          className="glass-panel animate-msg"
          role="status"
          style={{
            position: 'fixed',
            bottom: '24px',
            right: '20px',
            zIndex: 160,
            padding: '10px 18px',
            borderRadius: '8px',
            backgroundColor: toast.tone === 'success' ? 'var(--okq)' : 'var(--p0q)',
            border: `1px solid ${toast.tone === 'success' ? 'var(--ok)' : 'var(--p0)'}`,
            color: toast.tone === 'success' ? 'var(--ok)' : 'var(--p0)',
            fontSize: '12.5px',
            fontWeight: 600,
            boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
            maxWidth: 'min(420px, calc(100vw - 40px))',
          }}
        >
          {toast.message}
        </div>
      ), document.body)}

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

      {/* Gate Recognition Confidence Threshold Setting Card */}
      <div
        style={{
          margin: '16px 22px 8px 22px',
          padding: '16px 18px',
          borderRadius: '12px',
          backgroundColor: 'rgba(255, 255, 255, 0.02)',
          border: '1px solid var(--line)',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          background: 'linear-gradient(135deg, rgba(37, 99, 235, 0.05) 0%, rgba(0, 0, 0, 0.0) 100%)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                backgroundColor: 'var(--accq)',
                color: 'var(--acc)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '16px',
              }}
            >
              🎯
            </div>
            <div>
              <div style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--ink)' }}>
                Ngưỡng độ chính xác tối thiểu ghi nhận sự kiện (Giám sát Cổng)
              </div>
              <div style={{ fontSize: '12px', color: 'var(--ink2)', marginTop: '2px' }}>
                Chỉ các biển số đạt tỉ lệ chính xác từ mức này trở lên mới được lưu vào hệ thống và hiển thị ở danh sách bên phải.
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '4px 12px',
                borderRadius: '8px',
                backgroundColor: minConfidence >= 85 ? 'var(--okq)' : minConfidence >= 70 ? 'var(--accq)' : 'var(--p0q)',
                border: `1px solid ${minConfidence >= 85 ? 'var(--ok)' : minConfidence >= 70 ? 'var(--acc)' : 'var(--p0)'}`,
                color: minConfidence >= 85 ? 'var(--ok)' : minConfidence >= 70 ? 'var(--acc)' : 'var(--p0)',
                fontFamily: 'var(--font-mono)',
                fontSize: '14px',
                fontWeight: 700,
              }}
            >
              <span>{minConfidence}%</span>
              <span style={{ fontSize: '11px', fontWeight: 500, opacity: 0.85 }}>
                {minConfidence >= 85 ? '• Khắt khe' : minConfidence >= 70 ? '• Khuyên dùng' : '• Nhạy'}
              </span>
            </div>

            <button
              onClick={() => handleSaveConfidence(minConfidence)}
              disabled={isSavingConfig}
              style={{
                padding: '6px 14px',
                borderRadius: '7px',
                border: 'none',
                backgroundColor: 'var(--acc)',
                color: '#ffffff',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                opacity: isSavingConfig ? 0.7 : 1,
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
              }}
            >
              {isSavingConfig ? 'Đang lưu...' : 'Lưu cấu hình'}
            </button>
          </div>
        </div>

        {/* Slider & Quick Presets */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap', paddingTop: '4px' }}>
          <div style={{ flex: '1 1 280px', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '11.5px', fontFamily: 'var(--font-mono)', color: 'var(--ink3)' }}>50%</span>
            <div style={{ position: 'relative', flex: 1, paddingTop: '24px' }}>
              <span
                aria-hidden="true"
                style={{
                  position: 'absolute',
                  top: 0,
                  left: `calc(${((minConfidence - 50) / 45) * 100}% + ${8 - ((minConfidence - 50) / 45) * 16}px)`,
                  transform: 'translateX(-50%)',
                  minWidth: '38px',
                  padding: '2px 6px',
                  borderRadius: '5px',
                  backgroundColor: minConfidence >= 85 ? 'var(--ok)' : 'var(--acc)',
                  color: '#ffffff',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  fontWeight: 700,
                  textAlign: 'center',
                  pointerEvents: 'none',
                }}
              >
                {minConfidence}%
              </span>
              <input
                type="range"
                min="50"
                max="95"
                step="1"
                value={minConfidence}
                aria-label="Ngưỡng độ chính xác tối thiểu"
                aria-valuetext={`${minConfidence}%`}
                onChange={(e) => setMinConfidence(Number(e.target.value))}
                style={{
                  display: 'block',
                  width: '100%',
                  margin: 0,
                  cursor: 'pointer',
                  accentColor: minConfidence >= 85 ? 'var(--ok)' : 'var(--acc)',
                }}
              />
            </div>
            <span style={{ fontSize: '11.5px', fontFamily: 'var(--font-mono)', color: 'var(--ink3)' }}>95%</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: '11.5px', color: 'var(--ink3)', marginRight: '4px' }}>Mức nhanh:</span>
            {[
              { val: 60, label: '60% (Nhạy)' },
              { val: 70, label: '70% (Chuẩn)' },
              { val: 80, label: '80% (Cao)' },
              { val: 85, label: '85% (Nghiêm ngặt)' },
            ].map((preset) => (
              <button
                key={preset.val}
                onClick={() => {
                  setMinConfidence(preset.val);
                  handleSaveConfidence(preset.val);
                }}
                style={{
                  padding: '3px 8px',
                  borderRadius: '5px',
                  border: `1px solid ${minConfidence === preset.val ? 'var(--acc)' : 'var(--line)'}`,
                  backgroundColor: minConfidence === preset.val ? 'var(--accq)' : 'transparent',
                  color: minConfidence === preset.val ? 'var(--acc)' : 'var(--ink2)',
                  fontSize: '11px',
                  fontWeight: minConfidence === preset.val ? 600 : 400,
                  cursor: 'pointer',
                }}
              >
                {preset.label}
              </button>
            ))}
          </div>
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
            placeholder="Tìm theo biển số, thời gian…"
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
              onClick={() => changeStatusFilter('all')}
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
              onClick={() => changeStatusFilter('quen')}
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
              onClick={() => changeStatusFilter('la')}
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

        <div style={{ flex: 1 }} />

        <button
          type="button"
          onClick={handleResetDemo}
          disabled={isDeleting}
          title="Chỉ khả dụng trong môi trường demo local"
          style={{
            border: '1px solid var(--line2)',
            backgroundColor: 'transparent',
            color: 'var(--ink2)',
            borderRadius: '7px',
            padding: '6px 10px',
            fontSize: '11.5px',
            fontWeight: 600,
            cursor: isDeleting ? 'wait' : 'pointer',
          }}
        >
          Đặt lại demo
        </button>

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

      {selectedPlates.size > 0 && (
        <div
          role="status"
          style={{
            position: 'sticky',
            top: '76px',
            zIndex: 12,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            padding: '9px 22px',
            borderBottom: '1px solid var(--line)',
            backgroundColor: 'var(--panel)',
            boxShadow: '0 4px 10px rgba(0,0,0,0.08)',
          }}
        >
          <span style={{ color: 'var(--ink2)', fontSize: '12.5px', fontWeight: 600 }}>
            Đã chọn {selectedPlates.size} biển số
          </span>
          <button
            type="button"
            onClick={() => requestDelete(Array.from(selectedPlates))}
            disabled={isDeleting}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '7px',
              border: '1px solid var(--p0)',
              backgroundColor: 'var(--p0q)',
              color: 'var(--p0)',
              borderRadius: '7px',
              padding: '7px 11px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: isDeleting ? 'wait' : 'pointer',
            }}
          >
            <Trash2 size={14} aria-hidden="true" />
            Xóa các biển số đã chọn
          </button>
        </div>
      )}

      {/* Table Header with Sort Arrows */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '34px 70px 1.4fr 0.7fr 1fr 190px',
          padding: 'var(--table-py, 12px) var(--table-px, 22px)',
          borderBottom: '1px solid var(--line)',
          fontSize: '11.5px',
          color: 'var(--ink3)',
          fontWeight: 700,
          backgroundColor: 'var(--raise)',
          letterSpacing: '0.04em',
        }}
      >
        <div>
          <input
            type="checkbox"
            aria-label="Chọn tất cả biển số đang hiển thị"
            checked={paginatedVehicles.length > 0 && paginatedVehicles.every((vehicle) => selectedPlates.has(vehicle.plate))}
            onChange={(event) => {
              setSelectedPlates((current) => {
                const next = new Set(current);
                paginatedVehicles.forEach((vehicle) => {
                  if (event.target.checked) next.add(vehicle.plate);
                  else next.delete(vehicle.plate);
                });
                return next;
              });
            }}
          />
        </div>
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
          paginatedVehicles.map((v) => {
            const isStranger = (labelMap[v.plate] || 'la') === 'la';
            const tagLabel = isStranger ? 'Xe lạ (Cảnh báo)' : 'Xe quen (Hợp lệ)';
            const tagColor = isStranger ? 'var(--p0)' : 'var(--ok)';
            const tagBg = isStranger ? 'var(--p0q)' : 'var(--okq)';

            return (
              <div
                key={v.plate}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '34px 70px 1.4fr 0.7fr 1fr 190px',
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
                  <input
                    type="checkbox"
                    aria-label={`Chọn biển số ${v.plate}`}
                    checked={selectedPlates.has(v.plate)}
                    onChange={(event) => {
                      setSelectedPlates((current) => {
                        const next = new Set(current);
                        if (event.target.checked) next.add(v.plate);
                        else next.delete(v.plate);
                        return next;
                      });
                    }}
                  />
                </div>
                <div>
                  {v.cropPath ? (
                    <button
                      type="button"
                      title={`Xem ảnh crop biển số ${v.plate}`}
                      onClick={() => setSelectedCrop({ plate: v.plate, url: getCropImageUrl(v.cropPath) })}
                      style={{
                        width: '54px',
                        height: '34px',
                        padding: 0,
                        borderRadius: '7px',
                        border: '1px solid var(--line2)',
                        overflow: 'hidden',
                        cursor: 'pointer',
                        backgroundColor: 'var(--raise)',
                      }}
                    >
                      <img
                        src={getCropImageUrl(v.cropPath)}
                        alt={`Biển số ${v.plate}`}
                        style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                      />
                    </button>
                  ) : (
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
                    Chưa có
                  </div>
                  )}
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

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
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
                  <button
                    type="button"
                    onClick={() => requestDelete([v.plate])}
                    disabled={isDeleting}
                    title={`Xóa biển số ${v.plate}`}
                    aria-label={`Xóa biển số ${v.plate}`}
                    onMouseEnter={(event) => {
                      event.currentTarget.style.borderColor = 'var(--p0)';
                      event.currentTarget.style.backgroundColor = 'var(--p0q)';
                      event.currentTarget.style.color = 'var(--p0)';
                    }}
                    onMouseLeave={(event) => {
                      event.currentTarget.style.borderColor = 'var(--line2)';
                      event.currentTarget.style.backgroundColor = 'transparent';
                      event.currentTarget.style.color = 'var(--ink3)';
                    }}
                    style={{
                      width: '30px',
                      height: '30px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flex: '0 0 30px',
                      borderRadius: '7px',
                      border: '1px solid var(--line2)',
                      backgroundColor: 'transparent',
                      color: 'var(--ink3)',
                      cursor: isDeleting ? 'wait' : 'pointer',
                    }}
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {filteredVehicles.length > 0 && (
        <div
          aria-label="Phân trang danh sách biển số"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            padding: '10px 22px',
            borderTop: '1px solid var(--line)',
            backgroundColor: 'var(--panel)',
          }}
        >
          <span style={{ color: 'var(--ink3)', fontSize: '11.5px', fontFamily: 'var(--font-mono)' }}>
            Trang {currentPage} / {pageCount} · {filteredVehicles.length} biển số
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <button
              type="button"
              title="Trang trước"
              aria-label="Trang trước"
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
              style={{
                width: '32px', height: '32px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                border: '1px solid var(--line2)', borderRadius: '7px', backgroundColor: 'var(--raise)', color: 'var(--ink2)',
                cursor: currentPage <= 1 ? 'not-allowed' : 'pointer', opacity: currentPage <= 1 ? 0.45 : 1,
              }}
            >
              <ChevronLeft size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              title="Trang sau"
              aria-label="Trang sau"
              disabled={currentPage >= pageCount}
              onClick={() => setCurrentPage((page) => Math.min(pageCount, page + 1))}
              style={{
                width: '32px', height: '32px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                border: '1px solid var(--line2)', borderRadius: '7px', backgroundColor: 'var(--raise)', color: 'var(--ink2)',
                cursor: currentPage >= pageCount ? 'not-allowed' : 'pointer', opacity: currentPage >= pageCount ? 0.45 : 1,
              }}
            >
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      {pendingDeletePlates && createPortal((
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-vehicle-title"
          onClick={() => !isDeleting && setPendingDeletePlates(null)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 150,
            backgroundColor: 'rgba(0,0,0,0.62)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
        >
          <div
            className="glass-panel"
            onClick={(event) => event.stopPropagation()}
            style={{ width: 'min(420px, 100%)', padding: '20px', borderRadius: '8px' }}
          >
            <div id="delete-vehicle-title" style={{ color: 'var(--ink)', fontSize: '16px', fontWeight: 700 }}>
              Xác nhận xóa biển số
            </div>
            <div style={{ color: 'var(--ink2)', fontSize: '13px', lineHeight: 1.55, marginTop: '8px' }}>
              {pendingDeletePlates.length === 1
                ? `Bạn có chắc muốn xóa biển số ${pendingDeletePlates[0]} khỏi danh sách gắn nhãn?`
                : `Bạn có chắc muốn xóa ${pendingDeletePlates.length} biển số đã chọn khỏi danh sách gắn nhãn?`}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '20px' }}>
              <button
                type="button"
                onClick={() => setPendingDeletePlates(null)}
                disabled={isDeleting}
                style={{
                  border: '1px solid var(--line2)',
                  backgroundColor: 'transparent',
                  color: 'var(--ink2)',
                  borderRadius: '7px',
                  padding: '8px 14px',
                  cursor: isDeleting ? 'wait' : 'pointer',
                  fontWeight: 600,
                }}
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={isDeleting}
                style={{
                  border: '1px solid var(--p0)',
                  backgroundColor: 'var(--p0)',
                  color: '#fff',
                  borderRadius: '7px',
                  padding: '8px 14px',
                  cursor: isDeleting ? 'wait' : 'pointer',
                  fontWeight: 700,
                }}
              >
                {isDeleting ? 'Đang xóa...' : 'Xóa'}
              </button>
            </div>
          </div>
        </div>
      ), document.body)}

      {selectedCrop && createPortal((
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Ảnh crop biển số ${selectedCrop.plate}`}
          onClick={() => setSelectedCrop(null)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 120,
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
