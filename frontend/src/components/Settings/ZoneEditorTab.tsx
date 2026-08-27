import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import type {
  PolygonZone,
  ObjectLabel,
  ZoneMutationNotice,
  ZoneMutationStatus,
} from '../../types';
import { useCameraFeed } from '../../hooks/useCameraFeed';

interface ZoneEditorTabProps {
  clock: string;
  zonesByCam: Record<string, PolygonZone[]>;
  objLabels: ObjectLabel[];
  onUpdateZone: (camId: string, zoneId: string, patch: Partial<PolygonZone>) => void;
  onAddZone: (camId: string, newZone: PolygonZone) => Promise<PolygonZone>;
  onDeleteZone: (camId: string, zoneId: string) => void;
  mutationStatusByZoneId?: Record<string, ZoneMutationStatus>;
  mutationNotice?: ZoneMutationNotice | null;
  snapshotImageByCam?: Record<string, string | null>;
  snapshotImage?: string | null;
  isLoading: boolean;
  apiError: string | null;
  labelRegistryStatus: 'loading' | 'ready' | 'error';
  onRetry: () => void;
  activeCameraId?: string;
  onChangeCamera?: (camId: string) => void;
}

const PRESET_COLORS = [
  '#10b981', // Green
  '#3b82f6', // Blue
  '#f59e0b', // Amber/Orange
  '#f43f5e', // Red
  '#a855f7', // Purple
  '#06b6d4', // Cyan
  '#ec4899', // Pink
  '#eab308', // Yellow
  '#14b8a6'  // Teal
];

export const ZoneEditorTab: React.FC<ZoneEditorTabProps> = ({
  clock,
  zonesByCam,
  objLabels,
  onUpdateZone,
  onAddZone,
  onDeleteZone,
  mutationStatusByZoneId = {},
  mutationNotice,
  snapshotImageByCam,
  snapshotImage,
  isLoading,
  apiError,
  labelRegistryStatus,
  onRetry,
  activeCameraId,
  onChangeCamera,
}) => {
  const [camSel, setCamSel] = useState<string>(activeCameraId || 'GATE-01');
  const canMutateZones = labelRegistryStatus === 'ready';
  const { frameImage } = useCameraFeed(camSel);
  const [tool, setTool] = useState<'select' | 'draw'>('select');
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [selectedVertexIdx, setSelectedVertexIdx] = useState<number | null>(null);
  const [zoneSearch, setZoneSearch] = useState<string>('');
  const [zoneNameDrafts, setZoneNameDrafts] = useState<Record<string, string>>({});
  const registryLabelNames = useMemo(
    () => new Set(objLabels.map((label) => label.name.toLocaleLowerCase())),
    [objLabels],
  );

  // Toast / notification message
  const [toastMsg, setToastMsg] = useState<string>('');

  // Drawing state
  const [draftPoints, setDraftPoints] = useState<[number, number][]>([]);
  const [draftHover, setDraftHover] = useState<[number, number] | null>(null);

  // Undo / Redo History Stack per camera
  const [history, setHistory] = useState<PolygonZone[][]>([zonesByCam[camSel] || []]);
  const [historyIndex, setHistoryIndex] = useState<number>(0);
  const isUndoRedoActionRef = useRef<boolean>(false);

  // Color picker popup for specific zone
  const [colorPickerZoneId, setColorPickerZoneId] = useState<string | null>(null);

  // Card element refs for auto-scrolling
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Dragging state
  const dragRef = useRef<{
    mode: 'vertex' | 'move';
    zoneId: string;
    idx?: number;
    startX: number;
    startY: number;
    origPoints: [number, number][];
    hasMoved?: boolean;
  } | null>(null);
  const dragPreviewRef = useRef<{
    zoneId: string;
    points: [number, number][];
  } | null>(null);
  const [dragPreview, setDragPreview] = useState<{
    zoneId: string;
    points: [number, number][];
  } | null>(null);

  const feedRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (activeCameraId && activeCameraId !== camSel) {
      setCamSel(activeCameraId);
    }
  }, [activeCameraId, camSel]);

  const handleSwitchCamera = (newCamId: string) => {
    if (newCamId === camSel) return;
    setCamSel(newCamId);
    setSelectedZoneId(null);
    setSelectedVertexIdx(null);
    setTool('select');
    setDraftPoints([]);
    setDraftHover(null);
    setColorPickerZoneId(null);
    setZoneSearch('');
    onChangeCamera?.(newCamId);
  };

  const currentZones = useMemo(
    () => zonesByCam[camSel] ?? [],
    [zonesByCam, camSel],
  );
  const canvasZones = dragPreview
    ? currentZones.map((zone) => (
      zone.id === dragPreview.zoneId
        ? { ...zone, points: dragPreview.points }
        : zone
    ))
    : currentZones;
  const selectedZone = canvasZones.find((z) => z.id === selectedZoneId) || null;

  const activeSnapshot = snapshotImageByCam
    ? (snapshotImageByCam[camSel] || null)
    : (snapshotImage || null);

  // Filter zones by search keyword
  const displayedZones = useMemo(() => {
    if (!zoneSearch.trim()) return currentZones;
    const q = zoneSearch.toLowerCase().trim();
    return currentZones.filter((z) => z.name.toLowerCase().includes(q));
  }, [currentZones, zoneSearch]);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(''), 2500);
  };

  useEffect(() => {
    if (!isUndoRedoActionRef.current && !dragRef.current) {
      setHistory([zonesByCam[camSel] || []]);
      setHistoryIndex(0);
    }
  }, [camSel, zonesByCam]);

  useEffect(() => {
    if (apiError) {
      setToastMsg(apiError);
    }
  }, [apiError]);

  useEffect(() => {
    if (!mutationNotice) return;
    setToastMsg(mutationNotice.message);
    const timeout = window.setTimeout(() => setToastMsg(''), 2500);
    return () => window.clearTimeout(timeout);
  }, [mutationNotice]);

  // Auto-scroll right panel when a zone is selected on the left
  useEffect(() => {
    if (selectedZoneId && cardRefs.current[selectedZoneId]) {
      cardRefs.current[selectedZoneId]?.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest'
      });
    }
  }, [selectedZoneId]);

  // Push new state to history stack
  const pushHistory = useCallback(
    (newZones: PolygonZone[]) => {
      setHistory((prev) => {
        const sliced = prev.slice(0, historyIndex + 1);
        return [...sliced, newZones];
      });
      setHistoryIndex((prev) => prev + 1);
    },
    [historyIndex]
  );

  // Delete Vertex Handle
  const handleDeleteVertex = useCallback(
    (zoneId: string, idx: number) => {
      if (!canMutateZones) {
        showToast('⚠ Danh mục nhãn chưa sẵn sàng; mọi thay đổi Zone đang bị khóa.');
        return;
      }
      const zone = currentZones.find((z) => z.id === zoneId);
      if (!zone) return;
      if (zone.points.length <= 3) {
        showToast('⚠ Đa giác cần tối thiểu 3 đỉnh, không thể xóa thêm!');
        return;
      }

      const newPoints = zone.points.filter((_, i) => i !== idx);
      onUpdateZone(camSel, zoneId, { points: newPoints });
      const nextState = currentZones.map((z) => (z.id === zoneId ? { ...z, points: newPoints } : z));
      pushHistory(nextState);
      setSelectedVertexIdx(null);
    },
    [currentZones, camSel, onUpdateZone, pushHistory, canMutateZones]
  );

  // Delete entire Zone
  const handleDeleteZoneWithHistory = useCallback(
    (zoneId: string) => {
      if (!canMutateZones) {
        showToast('⚠ Danh mục nhãn chưa sẵn sàng; mọi thay đổi Zone đang bị khóa.');
        return;
      }
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      dragRef.current = null;
      dragPreviewRef.current = null;
      setDragPreview(null);
      onDeleteZone(camSel, zoneId);
      const nextState = currentZones.filter((z) => z.id !== zoneId);
      pushHistory(nextState);
      if (selectedZoneId === zoneId) {
        setSelectedZoneId(null);
        setSelectedVertexIdx(null);
      }
    },
    [currentZones, camSel, onDeleteZone, pushHistory, selectedZoneId, canMutateZones]
  );

  // Undo action
  const handleUndo = useCallback(() => {
    if (!canMutateZones) {
      showToast('⚠ Danh mục nhãn chưa sẵn sàng; mọi thay đổi Zone đang bị khóa.');
      return;
    }
    if (tool === 'draw' && draftPoints.length > 0) {
      setDraftPoints((prev) => prev.slice(0, -1));
      return;
    }

    if (historyIndex > 0) {
      isUndoRedoActionRef.current = true;
      const targetState = history[historyIndex - 1];
      setHistoryIndex((prev) => prev - 1);

      targetState.forEach((z) => {
        const existing = currentZones.find((curr) => curr.id === z.id);
        if (existing) {
          onUpdateZone(camSel, z.id, z);
        } else {
          onAddZone(camSel, z);
        }
      });
      currentZones.forEach((curr) => {
        if (!targetState.some((z) => z.id === curr.id)) {
          onDeleteZone(camSel, curr.id);
        }
      });
      setSelectedVertexIdx(null);
    }
  }, [tool, draftPoints, historyIndex, history, currentZones, camSel, onUpdateZone, onAddZone, onDeleteZone, canMutateZones]);

  // Redo action
  const handleRedo = useCallback(() => {
    if (!canMutateZones) {
      showToast('⚠ Danh mục nhãn chưa sẵn sàng; mọi thay đổi Zone đang bị khóa.');
      return;
    }
    if (historyIndex < history.length - 1) {
      isUndoRedoActionRef.current = true;
      const targetState = history[historyIndex + 1];
      setHistoryIndex((prev) => prev + 1);

      targetState.forEach((z) => {
        const existing = currentZones.find((curr) => curr.id === z.id);
        if (existing) {
          onUpdateZone(camSel, z.id, z);
        } else {
          onAddZone(camSel, z);
        }
      });
      currentZones.forEach((curr) => {
        if (!targetState.some((z) => z.id === curr.id)) {
          onDeleteZone(camSel, curr.id);
        }
      });
      setSelectedVertexIdx(null);
    }
  }, [historyIndex, history, currentZones, camSel, onUpdateZone, onAddZone, onDeleteZone, canMutateZones]);

  // Complete zone drawing
  const handleFinishDraw = useCallback(async () => {
    if (labelRegistryStatus !== 'ready') {
      showToast('⚠ Chưa thể tạo Zone vì danh mục nhãn chưa sẵn sàng.');
      return;
    }
    if (draftPoints.length < 3) return;
    const newId = 'z' + Date.now();
    const newColor = PRESET_COLORS[currentZones.length % PRESET_COLORS.length];

    const defaultTypes: Record<string, number> = {};
    objLabels.forEach((l) => {
      if (l.isDetectable) defaultTypes[l.name] = 0;
    });

    const newZone: PolygonZone = {
      id: newId,
      name: `Zone mới ${currentZones.length + 1}`,
      color: newColor,
      points: draftPoints,
      types: defaultTypes
    };

    try {
      const persistedZone = await onAddZone(camSel, newZone);
      const nextState = [...currentZones, persistedZone];
      pushHistory(nextState);

      setSelectedZoneId(persistedZone.id);
      setSelectedVertexIdx(null);
      setTool('select');
      setDraftPoints([]);
      setDraftHover(null);
    } catch (error) {
      if (!(error instanceof Error && error.message === 'ZONE_CREATE_CANCELLED')) {
        // The mutation coordinator publishes the server-confirmed error message.
      }
    }
  }, [draftPoints, currentZones, objLabels, camSel, onAddZone, pushHistory, labelRegistryStatus]);

  // Keyboard shortcut listener for Enter, Escape, Ctrl+Z, Ctrl+Y, Delete, Backspace
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }

      // Enter: Complete drawing zone if in draw mode and draftPoints >= 3
      if (e.key === 'Enter') {
        if (tool === 'draw' && draftPoints.length >= 3) {
          e.preventDefault();
          handleFinishDraw();
        }
      }
      // Escape: Cancel drawing zone
      else if (e.key === 'Escape') {
        if (tool === 'draw') {
          e.preventDefault();
          setDraftPoints([]);
          setDraftHover(null);
          setTool('select');
        }
      }
      // Undo: Ctrl+Z
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      }
      // Redo: Ctrl+Y or Ctrl+Shift+Z
      else if (
        (e.ctrlKey || e.metaKey) &&
        (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))
      ) {
        e.preventDefault();
        handleRedo();
      }
      // Delete / Backspace: Delete selected vertex or selected zone
      else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (tool === 'select') {
          if (selectedVertexIdx !== null && selectedZoneId) {
            e.preventDefault();
            handleDeleteVertex(selectedZoneId, selectedVertexIdx);
          } else if (selectedZoneId) {
            e.preventDefault();
            handleDeleteZoneWithHistory(selectedZoneId);
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    handleUndo,
    handleRedo,
    handleFinishDraw,
    tool,
    draftPoints.length,
    selectedVertexIdx,
    selectedZoneId,
    handleDeleteVertex,
    handleDeleteZoneWithHistory
  ]);

  // Convert mouse event to percentage (0 - 100)
  const getPercentageCoords = useCallback((e: React.MouseEvent): [number, number] | null => {
    if (!feedRef.current) return null;
    const rect = feedRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
    const y = Math.max(0, Math.min(100, ((e.clientY - rect.top) / rect.height) * 100));
    return [+x.toFixed(1), +y.toFixed(1)];
  }, []);

  const handleFeedMouseDown = (e: React.MouseEvent) => {
    if (tool === 'draw') {
      const p = getPercentageCoords(e);
      if (!p) return;

      if (draftPoints.length >= 3) {
        const first = draftPoints[0];
        if (Math.abs(p[0] - first[0]) < 3 && Math.abs(p[1] - first[1]) < 3) {
          handleFinishDraw();
          return;
        }
      }

      setDraftPoints((prev) => [...prev, p]);
    } else {
      // Clicked on background feed / empty area -> deselect
      if (e.target === feedRef.current || (e.target as HTMLElement).tagName === 'svg') {
        setSelectedZoneId(null);
        setSelectedVertexIdx(null);
        setColorPickerZoneId(null);
      }
    }
  };

  const handleFeedMouseMove = (e: React.MouseEvent) => {
    const p = getPercentageCoords(e);
    if (!p) return;

    if (tool === 'draw') {
      if (draftPoints.length > 0) {
        setDraftHover(p);
      }
      return;
    }

    const drag = dragRef.current;
    if (!drag) return;
    drag.hasMoved = true;

    let newPoints: [number, number][];
    if (drag.mode === 'vertex' && drag.idx !== undefined) {
      newPoints = drag.origPoints.map((point, index) => (
        index === drag.idx ? p : point
      )) as [number, number][];
    } else if (drag.mode === 'move') {
      const dx = p[0] - drag.startX;
      const dy = p[1] - drag.startY;

      const minX = Math.min(...drag.origPoints.map((pt) => pt[0]));
      const maxX = Math.max(...drag.origPoints.map((pt) => pt[0]));
      const minY = Math.min(...drag.origPoints.map((pt) => pt[1]));
      const maxY = Math.max(...drag.origPoints.map((pt) => pt[1]));

      const clampedDx = Math.max(1 - minX, Math.min(99 - maxX, dx));
      const clampedDy = Math.max(1 - minY, Math.min(99 - maxY, dy));

      newPoints = drag.origPoints.map(([x, y]) => [
        +Math.max(0, Math.min(100, x + clampedDx)).toFixed(1),
        +Math.max(0, Math.min(100, y + clampedDy)).toFixed(1)
      ]) as [number, number][];
    } else {
      return;
    }

    const preview = { zoneId: drag.zoneId, points: newPoints };
    dragPreviewRef.current = preview;

    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        if (dragPreviewRef.current) {
          setDragPreview(dragPreviewRef.current);
        }
        rafRef.current = null;
      });
    }
  };

  const handleFeedMouseUp = () => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    const drag = dragRef.current;
    const preview = dragPreviewRef.current;
    if (canMutateZones && drag && drag.hasMoved && preview?.zoneId === drag.zoneId) {
      const nextState = currentZones.map((zone) => (
        zone.id === drag.zoneId ? { ...zone, points: preview.points } : zone
      ));
      onUpdateZone(camSel, drag.zoneId, { points: preview.points });
      pushHistory(nextState);
    }
    dragRef.current = null;
    dragPreviewRef.current = null;
    setDragPreview(null);
  };

  const handleUpdateZoneProp = (zoneId: string, patch: Partial<PolygonZone>) => {
    if (!canMutateZones) {
      showToast('⚠ Danh mục nhãn chưa sẵn sàng; mọi thay đổi Zone đang bị khóa.');
      return;
    }
    onUpdateZone(camSel, zoneId, patch);
    const nextState = currentZones.map((z) => (z.id === zoneId ? { ...z, ...patch } : z));
    pushHistory(nextState);
  };

  const commitZoneName = useCallback((zoneId: string) => {
    if (!canMutateZones) {
      setZoneNameDrafts((previous) => {
        const { [zoneId]: _discardedDraft, ...remainingDrafts } = previous;
        return remainingDrafts;
      });
      showToast('⚠ Danh mục nhãn chưa sẵn sàng; đổi tên Zone đã bị hủy.');
      return;
    }
    const draftName = zoneNameDrafts[zoneId];
    if (draftName === undefined) return;

    const zone = currentZones.find((candidate) => candidate.id === zoneId);
    if (!zone) return;

    const nextName = draftName.trim();
    if (!nextName) {
      setZoneNameDrafts((previous) => ({ ...previous, [zoneId]: zone.name }));
      showToast('Tên zone không được để trống.');
      return;
    }

    if (nextName !== zone.name) {
      onUpdateZone(camSel, zoneId, { name: nextName });
      pushHistory(
        currentZones.map((candidate) => (
          candidate.id === zoneId ? { ...candidate, name: nextName } : candidate
        )),
      );
    }

    setZoneNameDrafts((previous) => {
      const { [zoneId]: _committedDraft, ...remainingDrafts } = previous;
      return remainingDrafts;
    });
  }, [camSel, currentZones, onUpdateZone, pushHistory, zoneNameDrafts, canMutateZones]);

  const canUndo = (tool === 'draw' && draftPoints.length > 0) || historyIndex > 0;
  const canRedo = historyIndex < history.length - 1;
  const isDragging = Boolean(dragPreview);

  return (
    <div
      aria-busy={labelRegistryStatus === 'loading'}
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.55fr) minmax(380px, 1fr)',
        gap: '18px',
        alignItems: 'start'
      }}
    >
      {labelRegistryStatus !== 'ready' && (
        <div role="alert" style={{ gridColumn: '1 / -1', border: '1px solid var(--p1)', background: 'var(--p1q)', color: 'var(--p1)', borderRadius: '10px', padding: '10px 12px', fontSize: '11.5px', lineHeight: 1.45 }}>
          {labelRegistryStatus === 'loading'
            ? 'Đang tải danh mục nhãn. Mọi thao tác lưu Zone tạm thời bị khóa.'
            : 'Không tải được danh mục nhãn. Mọi thao tác tạo, sửa và xóa Zone đã bị khóa để bảo toàn targetLabels.'}
        </div>
      )}
      {/* Left: Feed & Controls */}
      <div>
        {/* Controls Toolbar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            marginBottom: '12px',
            flexWrap: 'wrap'
          }}
        >
          {/* Camera scope Switcher */}
          <div
            className="glass-card"
            style={{
              display: 'flex',
              borderRadius: '11px',
              padding: '3px',
              gap: '3px',
              background: 'var(--surface-overlay, rgba(255, 255, 255, 0.04))',
            }}
          >
            <button
              type="button"
              onClick={() => handleSwitchCamera('BAI-KIEM')}
              title="Chuyển sang cấu hình Camera Bãi Kiểm"
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 13px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: camSel === 'BAI-KIEM' ? 'var(--acc)' : 'transparent',
                color: camSel === 'BAI-KIEM' ? '#fff' : 'var(--ink2)',
                transition: 'all 0.2s ease',
              }}
            >
              <span style={{ color: camSel === 'BAI-KIEM' ? '#fff' : 'var(--acc)' }}>●</span>
              Bãi Kiểm · BAI-KIEM
            </button>
            <button
              type="button"
              onClick={() => handleSwitchCamera('GATE-01')}
              title="Chuyển sang cấu hình Camera Giám sát Cổng"
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 13px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: camSel === 'GATE-01' ? 'var(--acc)' : 'transparent',
                color: camSel === 'GATE-01' ? '#fff' : 'var(--ink2)',
                transition: 'all 0.2s ease',
              }}
            >
              <span style={{ color: camSel === 'GATE-01' ? '#fff' : 'var(--acc)' }}>●</span>
              Giám sát cổng · GATE-01
            </button>
          </div>

          {/* Mode Switcher: Select vs Draw */}
          <div
            className="glass-card"
            style={{
              display: 'flex',
              borderRadius: '11px',
              padding: '3px',
              gap: '3px'
            }}
          >
            <button
              type="button"
              onClick={() => {
                setTool('select');
                setDraftPoints([]);
                setDraftHover(null);
              }}
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 14px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
                backgroundColor: tool === 'select' ? 'var(--acc)' : 'transparent',
                color: tool === 'select' ? '#fff' : 'var(--ink2)'
              }}
            >
              Chọn / Sửa
            </button>
            <button
              type="button"
              disabled={!canMutateZones}
              aria-disabled={!canMutateZones}
              onClick={() => {
                setTool('draw');
                setSelectedZoneId(null);
                setSelectedVertexIdx(null);
              }}
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 14px',
                borderRadius: '8px',
                border: 'none',
                cursor: canMutateZones ? 'pointer' : 'not-allowed',
                fontFamily: 'inherit',
                backgroundColor: tool === 'draw' ? 'var(--acc)' : 'transparent',
                color: canMutateZones ? (tool === 'draw' ? '#fff' : 'var(--ink2)') : 'var(--ink3)'
              }}
            >
              + Vẽ zone mới
            </button>
          </div>

          {/* Undo / Redo Buttons */}
          <div
            className="glass-card"
            style={{
              display: 'flex',
              borderRadius: '11px',
              padding: '3px',
              gap: '3px'
            }}
          >
            <button
              onClick={handleUndo}
              disabled={!canMutateZones || !canUndo}
              title="Hoàn tác (Ctrl+Z)"
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 10px',
                borderRadius: '8px',
                border: 'none',
                cursor: canMutateZones && canUndo ? 'pointer' : 'not-allowed',
                backgroundColor: 'transparent',
                color: canMutateZones && canUndo ? 'var(--ink)' : 'var(--ink3)',
                display: 'flex',
                alignItems: 'center',
                gap: '5px'
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M3 7v6h6" />
                <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" />
              </svg>
              <span>Undo</span>
            </button>
            <button
              onClick={handleRedo}
              disabled={!canMutateZones || !canRedo}
              title="Làm lại (Ctrl+Y)"
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 10px',
                borderRadius: '8px',
                border: 'none',
                cursor: canMutateZones && canRedo ? 'pointer' : 'not-allowed',
                backgroundColor: 'transparent',
                color: canMutateZones && canRedo ? 'var(--ink)' : 'var(--ink3)',
                display: 'flex',
                alignItems: 'center',
                gap: '5px'
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M21 7v6h-6" />
                <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3L21 13" />
              </svg>
              <span>Redo</span>
            </button>
          </div>

          {/* Drawing Actions */}
          {tool === 'draw' && draftPoints.length >= 3 && (
            <button
              onClick={handleFinishDraw}
              title="Hoàn tất và lưu zone (Phím Enter)"
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '7px 16px',
                borderRadius: '10px',
                border: 'none',
                backgroundColor: 'var(--ok)',
                color: '#fff',
                cursor: 'pointer',
                fontFamily: 'inherit',
                boxShadow: '0 2px 8px rgba(16, 185, 129, 0.4)',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <span>✓ Hoàn tất zone (Enter)</span>
            </button>
          )}

          {tool === 'draw' && draftPoints.length > 0 && (
            <button
              onClick={() => {
                setDraftPoints([]);
                setDraftHover(null);
              }}
              title="Hủy các điểm đang vẽ (Phím Escape)"
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '7px 14px',
                borderRadius: '10px',
                border: '1px solid var(--line2)',
                backgroundColor: 'transparent',
                color: 'var(--ink2)',
                cursor: 'pointer',
                fontFamily: 'inherit'
              }}
            >
              Hủy
            </button>
          )}

          <button
            onClick={onRetry}
            title="Tải lại zone và ảnh camera"
            style={{
              fontSize: '12px',
              fontWeight: 600,
              padding: '7px 12px',
              borderRadius: '10px',
              border: '1px solid var(--line2)',
              backgroundColor: 'transparent',
              color: 'var(--ink2)',
              cursor: 'pointer',
              fontFamily: 'inherit'
            }}
          >
            Tải lại
          </button>
        </div>

        {/* Interactive Feed Canvas */}
        <div
          ref={feedRef}
          onMouseDown={handleFeedMouseDown}
          onMouseMove={handleFeedMouseMove}
          onMouseUp={handleFeedMouseUp}
          onMouseLeave={handleFeedMouseUp}
          style={{
            position: 'relative',
            width: '100%',
            aspectRatio: '16/9',
            backgroundColor: '#07090c',
            border: '1px solid var(--line2)',
            borderRadius: '16px',
            overflow: 'hidden',
            cursor: tool === 'draw' ? 'crosshair' : 'default',
            userSelect: 'none',
            boxShadow: 'var(--shadow-lg)'
          }}
        >
          {/* Feed Background Image (Live Stream Frame or Video Snapshot or Asset) */}
          {frameImage ? (
            <img
              src={frameImage}
              alt="Live Camera Frame"
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                objectFit: 'contain',
                pointerEvents: 'none'
              }}
            />
          ) : (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                backgroundImage: activeSnapshot
                  ? `url('${activeSnapshot}')`
                  : camSel === 'GATE-01'
                    ? "url('/assets/cam-gate.png')"
                    : "url('/assets/cam-baikiem.png')",
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                pointerEvents: 'none'
              }}
            />
          )}
          <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(5, 8, 12, 0.12)', pointerEvents: 'none' }} />

          {/* Camera Info Overlay */}
          <div
            className="glass-panel"
            style={{
              position: 'absolute',
              left: '12px',
              top: '12px',
              color: '#ffffff',
              fontSize: '11px',
              padding: '4px 10px',
              borderRadius: '7px',
              fontFamily: 'var(--font-mono)',
              pointerEvents: 'none'
            }}
          >
            {camSel} · {camSel === 'GATE-01' ? 'Giám sát cổng' : 'Bãi Kiểm'}
          </div>

          <div
            className="glass-panel"
            style={{
              position: 'absolute',
              right: '12px',
              bottom: '12px',
              color: 'var(--ink2)',
              fontSize: '10.5px',
              padding: '4px 10px',
              borderRadius: '7px',
              fontFamily: 'var(--font-mono)',
              pointerEvents: 'none'
            }}
          >
            {clock} · Trình cấu hình Zone
          </div>

          {/* Toast message overlay on canvas */}
          {toastMsg && (
            <div
              className="animate-msg"
              style={{
                position: 'absolute',
                top: '16px',
                left: '50%',
                transform: 'translateX(-50%)',
                backgroundColor: 'rgba(15, 23, 42, 0.92)',
                backdropFilter: 'blur(8px)',
                border: '1px solid var(--line2)',
                color: '#ffffff',
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 16px',
                borderRadius: '20px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
                zIndex: 40,
                pointerEvents: 'none'
              }}
            >
              {toastMsg}
            </div>
          )}

          {isLoading && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'grid',
                placeItems: 'center',
                backgroundColor: 'rgba(5, 8, 12, 0.58)',
                color: 'var(--ink2)',
                fontSize: '13px',
                fontWeight: 600,
                zIndex: 35,
                pointerEvents: 'none'
              }}
            >
              Đang tải zone và ảnh camera…
            </div>
          )}

          {/* SVG Polygons and Draft */}
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
            {canvasZones.map((z) => {
              const isSelected = selectedZoneId === z.id;
              const pointsStr = z.points.map((p) => `${p[0]},${p[1]}`).join(' ');

              return (
                <polygon
                  key={z.id}
                  points={pointsStr}
                  fill={`${z.color}${isSelected ? '38' : '16'}`}
                  stroke={isSelected ? '#ffffff' : z.color}
                  strokeWidth={isSelected ? '2.8' : '1.6'}
                  strokeDasharray={isSelected ? '0' : '6 4'}
                  vectorEffect="non-scaling-stroke"
                  style={{
                    cursor: tool === 'select' ? (isSelected ? 'move' : 'pointer') : 'crosshair',
                    pointerEvents: 'auto',
                    filter: isSelected ? `drop-shadow(0 0 8px ${z.color})` : 'none',
                    transition: isDragging ? 'none' : 'fill 0.15s ease, stroke 0.15s ease'
                  }}
                  onMouseDown={(e) => {
                    if (tool !== 'select') return;
                    e.stopPropagation();
                    const p = getPercentageCoords(e);
                    if (!p) return;

                    // FIRST CLICK ON UNSELECTED ZONE: Select only! (Tránh kéo nhầm)
                    if (!isSelected) {
                      setSelectedZoneId(z.id);
                      setSelectedVertexIdx(null);
                      return;
                    }

                    // ALREADY SELECTED: Now allow dragging the zone!
                    dragRef.current = {
                      mode: 'move',
                      zoneId: z.id,
                      startX: p[0],
                      startY: p[1],
                      origPoints: z.points.map((pt) => [...pt]),
                      hasMoved: false
                    };
                    dragPreviewRef.current = null;
                    setDragPreview(null);
                  }}
                />
              );
            })}

            {/* Drawing Draft Polygon */}
            {tool === 'draw' && draftPoints.length > 0 && (
              <polygon
                points={[...draftPoints, ...(draftHover ? [draftHover] : [])].map((p) => `${p[0]},${p[1]}`).join(' ')}
                fill="rgba(59, 130, 246, 0.22)"
                stroke="#3b82f6"
                strokeWidth="1.8"
                strokeDasharray="5 4"
                vectorEffect="non-scaling-stroke"
                style={{ pointerEvents: 'none' }}
              />
            )}
          </svg>

          {/* Zone Labels */}
          {canvasZones.map((z) => {
            const topPoint = z.points.reduce((prev, curr) => (curr[1] < prev[1] ? curr : prev), z.points[0]);
            const isSelected = selectedZoneId === z.id;

            return (
              <span
                key={`lbl-${z.id}`}
                style={{
                  position: 'absolute',
                  left: `${topPoint[0]}%`,
                  top: `${topPoint[1]}%`,
                  transform: isSelected ? 'translateY(-125%) scale(1.1)' : 'translateY(-115%) scale(1)',
                  backgroundColor: isSelected ? '#ffffff' : z.color,
                  color: isSelected ? '#000000' : '#ffffff',
                  fontSize: '9.5px',
                  fontWeight: 700,
                  padding: '2px 8px',
                  borderRadius: '4px',
                  whiteSpace: 'nowrap',
                  pointerEvents: 'none',
                  boxShadow: isSelected
                    ? '0 0 14px rgba(255,255,255,0.9), 0 2px 8px rgba(0,0,0,0.5)'
                    : '0 2px 8px rgba(0,0,0,0.5)',
                  transition: isDragging ? 'none' : 'transform 0.15s ease',
                  zIndex: 8
                }}
              >
                {z.name}
              </span>
            );
          })}

          {/* Handles for Selected Zone in Select Mode */}
          {tool === 'select' && selectedZone && (
            <>
              {/* Vertex Handles (Drag to change shape, Click to select, Right-click / Double-click to delete) */}
              {selectedZone.points.map((p, i) => {
                const isVertexSelected = selectedVertexIdx === i;

                return (
                  <span
                    key={`v-${i}`}
                    onMouseDown={(e) => {
                      e.stopPropagation();
                      setSelectedVertexIdx(i);
                      const coords = getPercentageCoords(e);
                      if (!coords) return;

                      // Start dragging this vertex
                      dragRef.current = {
                        mode: 'vertex',
                        zoneId: selectedZone.id,
                        idx: i,
                        startX: coords[0],
                        startY: coords[1],
                        origPoints: selectedZone.points.map((pt) => [...pt]),
                        hasMoved: false
                      };
                      dragPreviewRef.current = null;
                      setDragPreview(null);
                    }}
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      handleDeleteVertex(selectedZone.id, i);
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      handleDeleteVertex(selectedZone.id, i);
                    }}
                    title="Kéo để nắn hình · Nhấp đúp / Chuột phải hoặc bấm Delete để xóa góc này"
                    style={{
                      position: 'absolute',
                      left: `${p[0]}%`,
                      top: `${p[1]}%`,
                      width: isVertexSelected ? '15px' : '13px',
                      height: isVertexSelected ? '15px' : '13px',
                      margin: isVertexSelected ? '-7.5px 0 0 -7.5px' : '-6.5px 0 0 -6.5px',
                      backgroundColor: isVertexSelected ? 'var(--p0)' : '#ffffff',
                      border: isVertexSelected ? '2px solid #ffffff' : `2px solid ${selectedZone.color}`,
                      borderRadius: '3px',
                      cursor: 'grab',
                      boxShadow: isVertexSelected
                        ? '0 0 12px rgba(244, 63, 94, 0.9), 0 2px 6px rgba(0,0,0,0.6)'
                        : '0 2px 6px rgba(0,0,0,0.6)',
                      zIndex: 15,
                      transition: isDragging ? 'none' : 'transform 0.1s ease, width 0.1s ease, height 0.1s ease'
                    }}
                  />
                );
              })}

              {/* Edge Midpoint Handles (Drag to insert new vertex) */}
              {selectedZone.points.map((p, i) => {
                const nextP = selectedZone.points[(i + 1) % selectedZone.points.length];
                const midX = (p[0] + nextP[0]) / 2;
                const midY = (p[1] + nextP[1]) / 2;

                return (
                  <span
                    key={`e-${i}`}
                    onMouseDown={(e) => {
                      e.stopPropagation();
                      const coords = getPercentageCoords(e);
                      if (!coords) return;

                      // Insert new point in between
                      const newPoints = [...selectedZone.points];
                      newPoints.splice(i + 1, 0, [+midX.toFixed(1), +midY.toFixed(1)]);
                      const preview = {
                        zoneId: selectedZone.id,
                        points: newPoints as [number, number][],
                      };
                      dragPreviewRef.current = preview;
                      setDragPreview(preview);

                      setSelectedVertexIdx(i + 1);

                      dragRef.current = {
                        mode: 'vertex',
                        zoneId: selectedZone.id,
                        idx: i + 1,
                        startX: coords[0],
                        startY: coords[1],
                        origPoints: newPoints.map((pt) => [...pt]),
                        hasMoved: true
                      };
                    }}
                    title="Kéo điểm giữa để thêm góc mới"
                    style={{
                      position: 'absolute',
                      left: `${midX}%`,
                      top: `${midY}%`,
                      width: '11px',
                      height: '11px',
                      margin: '-5.5px 0 0 -5.5px',
                      backgroundColor: 'rgba(255,255,255,0.6)',
                      border: `1.5px dashed ${selectedZone.color}`,
                      borderRadius: '50%',
                      cursor: 'copy',
                      boxShadow: '0 1px 4px rgba(0,0,0,0.5)',
                      zIndex: 9
                    }}
                  />
                );
              })}
            </>
          )}

          {/* Draft Points Dots */}
          {tool === 'draw' &&
            draftPoints.map((p, i) => (
              <span
                key={`dp-${i}`}
                style={{
                  position: 'absolute',
                  left: `${p[0]}%`,
                  top: `${p[1]}%`,
                  width: '11px',
                  height: '11px',
                  margin: '-5.5px 0 0 -5.5px',
                  backgroundColor: '#3b82f6',
                  border: '2px solid #ffffff',
                  borderRadius: '50%',
                  pointerEvents: 'none',
                  zIndex: 10
                }}
              />
            ))}
        </div>

        {/* Helper Hint with Key Shortcuts */}
        <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--ink3)', display: 'flex', gap: '14px', flexWrap: 'wrap', padding: '0 4px' }}>
          <span>⌨️ <b>Enter</b> Hoàn tất zone vẽ</span>
          <span>•</span>
          <span><b>Ctrl+Z / Ctrl+Y</b> Hoàn tác / Làm lại</span>
          <span>•</span>
          <span><b>Delete / Backspace</b> Xóa Zone hoặc xóa đỉnh</span>
          <span>•</span>
          <span><b>Chuột phải / Nhấp đúp</b> xóa góc</span>
          <span>•</span>
          <span>{tool === 'draw' ? 'Bấm góc đầu hoặc ấn Enter để đóng đa giác' : 'Bấm chọn Zone trước khi kéo di chuyển (tránh kéo nhầm)'}</span>
        </div>
      </div>

      {/* Right: Zone Management Panel (Fixed Scrollable Container) */}
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
        {/* Panel Header with Zone Counter & Quick Search */}
        <div
          style={{
            padding: '14px 18px',
            borderBottom: '1px solid var(--line)',
            backgroundColor: 'var(--panel)'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--ink)' }}>Danh sách Zone</span>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '2px 8px',
                  borderRadius: '12px',
                  backgroundColor: 'var(--raise)',
                  color: 'var(--ink2)'
                }}
              >
                {displayedZones.length} / {currentZones.length} zone
              </span>
            </div>

            {selectedZone && (
              <span style={{ fontSize: '11.5px', color: 'var(--acc)', fontWeight: 600 }}>
                Đang chọn: {selectedZone.name}
              </span>
            )}
          </div>

          {/* Quick Search for Zones */}
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
              value={zoneSearch}
              onChange={(e) => setZoneSearch(e.target.value)}
              placeholder="Tìm theo tên zone…"
              style={{
                width: '100%',
                backgroundColor: 'var(--bg)',
                border: '1px solid var(--line2)',
                borderRadius: '8px',
                padding: '6px 10px 6px 30px',
                fontSize: '12px',
                color: 'var(--ink)',
                outline: 'none'
              }}
            />
            {zoneSearch && (
              <button
                onClick={() => setZoneSearch('')}
                style={{
                  position: 'absolute',
                  right: '8px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  backgroundColor: 'transparent',
                  border: 'none',
                  color: 'var(--ink3)',
                  cursor: 'pointer',
                  fontSize: '11px'
                }}
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Scrollable Zone Cards Stream */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '12px 14px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px'
          }}
        >
          {displayedZones.length === 0 ? (
            <div style={{ padding: '32px 18px', textAlign: 'center', color: 'var(--ink3)', fontSize: '12.5px' }}>
              Không tìm thấy zone nào phù hợp từ khóa
            </div>
          ) : (
            displayedZones.map((z) => {
              const isSelected = selectedZoneId === z.id;
              const isColorPickerOpen = colorPickerZoneId === z.id;
              const mutationStatus = mutationStatusByZoneId[z.id];
              const targetLabelKeys = new Set((z.targetLabels || []).map((label) => label.toLocaleLowerCase()));
              const unknownLegacyLabels = (z.targetLabels || []).filter(
                (label) => !registryLabelNames.has(label.toLocaleLowerCase()),
              );

              return (
                <div
                  key={z.id}
                  aria-busy={mutationStatus?.phase === 'saving' || mutationStatus?.phase === 'deleting'}
                  ref={(el) => {
                    cardRefs.current[z.id] = el;
                  }}
                  onClick={() => {
                    setSelectedZoneId(z.id);
                    setSelectedVertexIdx(null);
                  }}
                  className="glass-card"
                  style={{
                    borderRadius: '13px',
                    padding: '12px 14px',
                    cursor: 'pointer',
                    border: isSelected ? `2px solid ${z.color}` : '1px solid var(--line)',
                    backgroundColor: isSelected ? 'var(--card-hover)' : 'var(--card)',
                    boxShadow: isSelected ? `0 0 16px ${z.color}33` : 'var(--shadow-sm)',
                    transition: 'all 0.16s ease'
                  }}
                >
                  {/* Card Header */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '9px', marginBottom: '8px' }}>
                    {/* Color Swatch */}
                    <div style={{ position: 'relative' }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setColorPickerZoneId(isColorPickerOpen ? null : z.id);
                        }}
                        title="Bấm để đổi màu sắc zone"
                        style={{
                          width: '24px',
                          height: '24px',
                          borderRadius: '7px',
                          backgroundColor: z.color,
                          border: '2px solid rgba(255,255,255,0.4)',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
                          flex: 'none'
                        }}
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="#ffffff">
                          <path d="M12 3a9 9 0 0 0 0 18c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1.01-.23-.26-.38-.61-.38-.99 0-.83.67-1.5 1.5-1.5H16c2.76 0 5-2.24 5-5 0-4.42-4.03-8-9-8z" />
                        </svg>
                      </button>

                      {/* Color Palette Popover */}
                      {isColorPickerOpen && (
                        <div
                          onClick={(e) => e.stopPropagation()}
                          className="glass-panel"
                          style={{
                            position: 'absolute',
                            left: 0,
                            top: '30px',
                            borderRadius: '12px',
                            padding: '8px',
                            display: 'grid',
                            gridTemplateColumns: 'repeat(5, 1fr)',
                            gap: '5px',
                            zIndex: 40,
                            boxShadow: 'var(--shadow-lg)',
                            width: '155px'
                          }}
                        >
                          {PRESET_COLORS.map((c) => (
                            <button
                              key={c}
                              onClick={() => {
                                handleUpdateZoneProp(z.id, { color: c });
                                setColorPickerZoneId(null);
                              }}
                              style={{
                                width: '22px',
                                height: '22px',
                                borderRadius: '5px',
                                backgroundColor: c,
                                border: z.color === c ? '2px solid #ffffff' : '1px solid rgba(0,0,0,0.3)',
                                cursor: 'pointer',
                                padding: 0
                              }}
                            />
                          ))}
                          <label
                            title="Chọn màu tùy chỉnh"
                            style={{
                              width: '22px',
                              height: '22px',
                              borderRadius: '5px',
                              backgroundColor: 'var(--raise)',
                              border: '1px solid var(--line2)',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              cursor: 'pointer'
                            }}
                          >
                            <span style={{ fontSize: '10px', color: 'var(--ink)' }}>+</span>
                            <input
                              type="color"
                              value={z.color}
                              onChange={(e) => handleUpdateZoneProp(z.id, { color: e.target.value })}
                              style={{ opacity: 0, width: 0, height: 0, position: 'absolute' }}
                            />
                          </label>
                        </div>
                      )}
                    </div>

                    {/* Editable Zone Name */}
                    <input
                      value={zoneNameDrafts[z.id] ?? z.name}
                      onChange={(e) => {
                        const nextValue = e.target.value;
                        setZoneNameDrafts((previous) => ({ ...previous, [z.id]: nextValue }));
                      }}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          e.currentTarget.blur();
                        }
                      }}
                      placeholder="Tên zone…"
                      style={{
                        flex: 1,
                        minWidth: 0,
                        backgroundColor: 'transparent',
                        border: '1px solid transparent',
                        borderRadius: '6px',
                        padding: '3px 6px',
                        color: 'var(--ink)',
                        fontSize: '13px',
                        fontWeight: 700,
                        outline: 'none'
                      }}
                      onFocus={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--bg)';
                        e.currentTarget.style.borderColor = 'var(--line2)';
                      }}
                      onBlur={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent';
                        e.currentTarget.style.borderColor = 'transparent';
                        commitZoneName(z.id);
                      }}
                    />

                    {/* Vertices Count Badge */}
                    <span
                      style={{
                        fontSize: '10px',
                        color: 'var(--ink3)',
                        fontFamily: 'var(--font-mono)',
                        backgroundColor: 'var(--raise)',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        flex: 'none'
                      }}
                    >
                      {z.points.length} đỉnh
                    </span>

                    {mutationStatus && mutationStatus.phase !== 'saved' && (
                      <span
                        title={mutationStatus.message}
                        style={{
                          fontSize: '10px',
                          fontWeight: 700,
                          color: mutationStatus.phase === 'error' ? 'var(--p0)' : 'var(--acc)',
                          backgroundColor: mutationStatus.phase === 'error' ? 'var(--p0q)' : 'var(--acc-q)',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {mutationStatus.phase === 'saving'
                          ? 'Đang lưu…'
                          : mutationStatus.phase === 'deleting'
                            ? 'Đang xóa…'
                            : 'Lỗi lưu'}
                      </span>
                    )}

                    {/* Delete Zone Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteZoneWithHistory(z.id);
                      }}
                      style={{
                        fontSize: '10.5px',
                        fontWeight: 600,
                        padding: '3px 8px',
                        borderRadius: '6px',
                        border: '1px solid var(--p0)',
                        backgroundColor: 'transparent',
                        color: 'var(--p0)',
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        flex: 'none'
                      }}
                    >
                      Xóa
                    </button>
                  </div>

                  {/* Vehicle Permissions Matrix */}
                  <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap', marginTop: '4px' }}>
                    {objLabels.map((obj) => {
                      const isAllowed = !!z.types[obj.name];
                      const isLegacyReference = !obj.isDetectable && targetLabelKeys.has(obj.name.toLocaleLowerCase());
                      return (
                        <button
                          type="button"
                          key={obj.id}
                          disabled={!obj.isDetectable}
                          aria-disabled={!obj.isDetectable}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (!obj.isDetectable) return;
                            handleUpdateZoneProp(z.id, {
                              types: {
                                ...z.types,
                                [obj.name]: isAllowed ? 0 : 1
                              }
                            });
                          }}
                          title={!obj.isDetectable
                            ? `${obj.name}: ${obj.capabilityReason}`
                            : `Bấm để ${isAllowed ? 'cấm' : 'cho phép'} ${obj.name}`}
                          style={{
                            fontSize: '10.5px',
                            fontWeight: 600,
                            padding: '3px 9px',
                            borderRadius: '16px',
                            border: `1px solid ${!obj.isDetectable ? 'var(--p1)' : isAllowed ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`,
                            backgroundColor: !obj.isDetectable ? 'var(--p1q)' : isAllowed ? 'var(--okq)' : 'var(--p0q)',
                            color: !obj.isDetectable ? 'var(--p1)' : isAllowed ? 'var(--ok)' : 'var(--p0)',
                            cursor: obj.isDetectable ? 'pointer' : 'not-allowed',
                            opacity: obj.isDetectable ? 1 : 0.82,
                            fontFamily: 'inherit',
                            transition: 'all 0.15s ease'
                          }}
                        >
                          {!obj.isDetectable
                            ? `${isLegacyReference ? '⚠ Nhãn cũ' : '⊘ Chưa có model'} · ${obj.name}`
                            : isAllowed ? `✓ ${obj.name}` : `✕ ${obj.name}`}
                        </button>
                      );
                    })}
                  </div>
                  {(objLabels.some((label) => !label.isDetectable && targetLabelKeys.has(label.name.toLocaleLowerCase())) || unknownLegacyLabels.length > 0) && (
                    <div role="note" style={{ marginTop: '7px', color: 'var(--p1)', fontSize: '10px', lineHeight: 1.4 }}>
                      Zone này có tham chiếu nhãn cũ chưa nhận diện được
                      {unknownLegacyLabels.length > 0 ? ` hoặc không còn trong registry: ${unknownLegacyLabels.join(', ')}` : ''}.
                      {' '}Tham chiếu cũ được hiển thị để đối soát và sẽ không được đưa vào payload lưu mới.
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Panel Footer Note */}
        <div
          style={{
            padding: '10px 16px',
            borderTop: '1px solid var(--line)',
            backgroundColor: 'var(--bg-subtle)',
            fontSize: '11px',
            color: 'var(--ink3)'
          }}
        >
          Phương tiện mang nhãn <b style={{ color: 'var(--p0)' }}>Xe lạ</b> hoặc sai loại sẽ cảnh báo vi phạm khi vào zone.
        </div>
      </div>
    </div>
  );
};
