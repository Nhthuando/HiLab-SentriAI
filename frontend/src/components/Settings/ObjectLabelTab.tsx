import React, { useState, useRef, useCallback, useEffect } from 'react';
import type { ObjectLabel, AnnotationSource, AnnotationSample } from '../../types';

interface ObjectLabelTabProps {
  objLabels: ObjectLabel[];
  annSources: AnnotationSource[];
  annSamples: AnnotationSample[];
  onAddLabel: (name: string, kind: 'xe' | 'nguoi', tint?: string) => void;
  onRenameLabel: (id: string, newName: string, kind?: 'xe' | 'nguoi', tint?: string) => void;
  onDeleteLabel: (id: string) => void;
  onAddSample: (sample: Omit<AnnotationSample, 'id'>) => void;
  onUpdateSample: (id: string, patch: Partial<AnnotationSample>) => void;
  onDeleteSample: (id: string) => void;
  onSaveSamples: () => void;
}

type DragMode = 'draw' | 'move' | 'resize-tl' | 'resize-tr' | 'resize-bl' | 'resize-br';

export const ObjectLabelTab: React.FC<ObjectLabelTabProps> = ({
  objLabels,
  annSources,
  annSamples,
  onAddLabel,
  onRenameLabel,
  onDeleteLabel,
  onAddSample,
  onUpdateSample,
  onDeleteSample,
  onSaveSamples
}) => {
  const [activeSourceId, setActiveSourceId] = useState<string>(annSources[0]?.id || 'src1');
  const [selectedLabelId, setSelectedLabelId] = useState<string>(objLabels[0]?.id || 'l8');
  const [vidFrameIdx, setVidFrameIdx] = useState<number>(0);
  const [selectedSampleId, setSelectedSampleId] = useState<string | null>(null);

  // Crosshair guide lines
  const [crosshairPos, setCrosshairPos] = useState<{ x: number; y: number } | null>(null);

  // Draft box drawing
  const [draftBox, setDraftBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  
  // Dragging & Resizing interaction state
  const dragRef = useRef<{
    mode: DragMode;
    startX: number;
    startY: number;
    initialBox?: { x: number; y: number; w: number; h: number };
    sampleId?: string;
  } | null>(null);

  const feedRef = useRef<HTMLDivElement>(null);
  const [savedSuccessMsg, setSavedSuccessMsg] = useState<string>('');

  // Modal State for Add / Edit Label
  const [labelModalOpen, setLabelModalOpen] = useState<boolean>(false);
  const [editingLabel, setEditingLabel] = useState<ObjectLabel | null>(null);
  const [modalName, setModalName] = useState<string>('');
  const [modalKind, setModalKind] = useState<'xe' | 'nguoi'>('xe');
  const [modalTint, setModalTint] = useState<string>('#3b82f6');

  const colorPalette = [
    '#3b82f6', // Classic Blue
    '#10b981', // Emerald
    '#06b6d4', // Cyan
    '#a855f7', // Purple
    '#f59e0b', // Amber
    '#f43f5e', // Rose
    '#8b5cf6', // Violet
    '#64748b'  // Slate
  ];

  const currentSource = annSources.find((s) => s.id === activeSourceId) || annSources[0];
  const isVideo = currentSource.kind === 'video';
  const selectedLabel = objLabels.find((l) => l.id === selectedLabelId);

  const getLabelColor = (labelId: string) => {
    const l = objLabels.find((o) => o.id === labelId);
    return l?.tint || '#3b82f6';
  };

  const vidTicks = [
    { label: '00:12', pct: '8%' },
    { label: '00:47', pct: '31%' },
    { label: '01:23', pct: '55%' },
    { label: '02:05', pct: '82%' }
  ];

  // Number key shortcuts (1 - 8) & Delete/Backspace shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }

      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedSampleId) {
        onDeleteSample(selectedSampleId);
        setSelectedSampleId(null);
        return;
      }

      const num = parseInt(e.key, 10);
      if (!isNaN(num) && num >= 1 && num <= objLabels.length) {
        const targetLabel = objLabels[num - 1];
        if (targetLabel) {
          setSelectedLabelId(targetLabel.id);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [objLabels, selectedSampleId, onDeleteSample]);

  const getPercentageCoords = useCallback((e: React.MouseEvent): { x: number; y: number } | null => {
    if (!feedRef.current) return null;
    const rect = feedRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
    const y = Math.max(0, Math.min(100, ((e.clientY - rect.top) / rect.height) * 100));
    return { x: +x.toFixed(1), y: +y.toFixed(1) };
  }, []);

  // Canvas Mouse Down: Start Drawing or Deselect
  const handleCanvasMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const p = getPercentageCoords(e);
    if (!p) return;

    // Deselect sample if clicking empty canvas
    setSelectedSampleId(null);

    if (!selectedLabelId) return;

    dragRef.current = {
      mode: 'draw',
      startX: p.x,
      startY: p.y
    };
    setDraftBox({ x: p.x, y: p.y, w: 0, h: 0 });
  };

  // Sample Box Mouse Down: Start Moving
  const handleSampleMouseDown = (e: React.MouseEvent, sample: AnnotationSample) => {
    e.stopPropagation();
    if (e.button !== 0) return;
    const p = getPercentageCoords(e);
    if (!p) return;

    setSelectedSampleId(sample.id);

    dragRef.current = {
      mode: 'move',
      startX: p.x,
      startY: p.y,
      initialBox: { x: sample.x, y: sample.y, w: sample.w, h: sample.h },
      sampleId: sample.id
    };
  };

  // Handle Resize Corner Mouse Down
  const handleResizeMouseDown = (e: React.MouseEvent, sample: AnnotationSample, mode: DragMode) => {
    e.stopPropagation();
    if (e.button !== 0) return;
    const p = getPercentageCoords(e);
    if (!p) return;

    setSelectedSampleId(sample.id);

    dragRef.current = {
      mode,
      startX: p.x,
      startY: p.y,
      initialBox: { x: sample.x, y: sample.y, w: sample.w, h: sample.h },
      sampleId: sample.id
    };
  };

  // Mouse Move: Draw, Move, or Resize
  const handleMouseMove = (e: React.MouseEvent) => {
    const p = getPercentageCoords(e);
    if (!p) return;
    setCrosshairPos(p);

    if (!dragRef.current) return;

    const { mode, startX, startY, initialBox, sampleId } = dragRef.current;

    // 1. Drawing new box
    if (mode === 'draw') {
      const x = Math.min(startX, p.x);
      const y = Math.min(startY, p.y);
      const w = Math.abs(p.x - startX);
      const h = Math.abs(p.y - startY);
      setDraftBox({ x, y, w, h });
      return;
    }

    // 2. Moving existing box
    if (mode === 'move' && initialBox && sampleId) {
      const dx = p.x - startX;
      const dy = p.y - startY;
      let newX = +(initialBox.x + dx).toFixed(1);
      let newY = +(initialBox.y + dy).toFixed(1);

      // Boundary clamp
      newX = Math.max(0, Math.min(100 - initialBox.w, newX));
      newY = Math.max(0, Math.min(100 - initialBox.h, newY));

      onUpdateSample(sampleId, { x: newX, y: newY });
      return;
    }

    // 3. Resizing existing box from 4 corners
    if (initialBox && sampleId) {
      const dx = p.x - startX;
      const dy = p.y - startY;

      let newX = initialBox.x;
      let newY = initialBox.y;
      let newW = initialBox.w;
      let newH = initialBox.h;

      if (mode === 'resize-tl') {
        newX = Math.min(initialBox.x + initialBox.w - 2, initialBox.x + dx);
        newY = Math.min(initialBox.y + initialBox.h - 2, initialBox.y + dy);
        newW = initialBox.w + (initialBox.x - newX);
        newH = initialBox.h + (initialBox.y - newY);
      } else if (mode === 'resize-tr') {
        newY = Math.min(initialBox.y + initialBox.h - 2, initialBox.y + dy);
        newW = Math.max(2, initialBox.w + dx);
        newH = initialBox.h + (initialBox.y - newY);
      } else if (mode === 'resize-bl') {
        newX = Math.min(initialBox.x + initialBox.w - 2, initialBox.x + dx);
        newW = initialBox.w + (initialBox.x - newX);
        newH = Math.max(2, initialBox.h + dy);
      } else if (mode === 'resize-br') {
        newW = Math.max(2, initialBox.w + dx);
        newH = Math.max(2, initialBox.h + dy);
      }

      // Percentage clamp
      newX = Math.max(0, Math.min(100, +newX.toFixed(1)));
      newY = Math.max(0, Math.min(100, +newY.toFixed(1)));
      newW = Math.max(2, Math.min(100 - newX, +newW.toFixed(1)));
      newH = Math.max(2, Math.min(100 - newY, +newH.toFixed(1)));

      onUpdateSample(sampleId, { x: newX, y: newY, w: newW, h: newH });
    }
  };

  const handleMouseUp = () => {
    if (!dragRef.current) return;

    if (dragRef.current.mode === 'draw' && draftBox) {
      if (draftBox.w >= 2 && draftBox.h >= 2 && selectedLabelId) {
        onAddSample({
          labelId: selectedLabelId,
          srcId: currentSource.id,
          frame: isVideo ? vidFrameIdx : null,
          x: +draftBox.x.toFixed(1),
          y: +draftBox.y.toFixed(1),
          w: +draftBox.w.toFixed(1),
          h: +draftBox.h.toFixed(1),
          session: 1
        });
        setSavedSuccessMsg('');
      }
    }

    dragRef.current = null;
    setDraftBox(null);
  };

  const pendingSessionCount = annSamples.filter((s) => s.session === 1).length;

  const handleSave = () => {
    if (pendingSessionCount === 0) return;
    onSaveSamples();
    setSavedSuccessMsg(`✓ Đã lưu thành công ${pendingSessionCount} mẫu gắn nhãn!`);
  };

  // Open Modal to Add
  const handleOpenAddModal = () => {
    setEditingLabel(null);
    setModalName('');
    setModalKind('xe');
    setModalTint(colorPalette[objLabels.length % colorPalette.length]);
    setLabelModalOpen(true);
  };

  // Open Modal to Edit
  const handleOpenEditModal = (label: ObjectLabel) => {
    setEditingLabel(label);
    setModalName(label.name);
    setModalKind(label.kind);
    setModalTint(label.tint || '#3b82f6');
    setLabelModalOpen(true);
  };

  // Save Modal
  const handleSaveLabelModal = () => {
    if (!modalName.trim()) return;

    if (editingLabel) {
      onRenameLabel(editingLabel.id, modalName.trim(), modalKind, modalTint);
    } else {
      onAddLabel(modalName.trim(), modalKind, modalTint);
    }
    setLabelModalOpen(false);
  };

  // Filter boxes for current source and frame
  const visibleBoxes = annSamples.filter((s) => {
    if (s.srcId !== currentSource.id) return false;
    if (isVideo) {
      return s.frame === vidFrameIdx;
    }
    return true;
  });

  const selectedSample = annSamples.find((s) => s.id === selectedSampleId) || null;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.6fr) minmax(340px, 1fr)',
        gap: '18px',
        alignItems: 'start'
      }}
    >
      {/* Left Column: Media Feed, Sources, Video Timeline & Drawing Canvas */}
      <div>
        {/* Source Media Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--ink)' }}>
            Gắn mẫu đối tượng ({visibleBoxes.length} mẫu trên khung)
          </span>
          <span style={{ fontSize: '12px', color: 'var(--ink3)' }}>
            {selectedLabel
              ? `Nhãn: "${selectedLabel.name}". Bấm phím 1-${objLabels.length} để đổi nhanh nhãn.`
              : 'Chọn một nhãn ở danh mục bên phải.'}
          </span>
        </div>

        {/* Source Thumbnails Strip */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', overflowX: 'auto', paddingBottom: '3px' }}>
          {annSources.map((s) => {
            const isSel = s.id === activeSourceId;
            return (
              <button
                key={s.id}
                onClick={() => {
                  setActiveSourceId(s.id);
                  setSelectedSampleId(null);
                }}
                style={{
                  position: 'relative',
                  flex: 'none',
                  width: '110px',
                  height: '66px',
                  borderRadius: '11px',
                  border: isSel ? '2px solid var(--acc)' : '1px solid var(--line2)',
                  backgroundColor: 'var(--card)',
                  cursor: 'pointer',
                  overflow: 'hidden',
                  padding: 0,
                  boxShadow: isSel ? '0 0 14px var(--acc-glow)' : 'var(--shadow-sm)',
                  transition: 'all 0.16s ease'
                }}
              >
                {s.img ? (
                  <img
                    src={s.img}
                    alt={s.name}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                ) : (
                  <div
                    style={{
                      width: '100%',
                      height: '100%',
                      background: `linear-gradient(135deg, ${s.tint || '#2a3b4c'}, var(--bg))`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}
                  >
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--ink3)" strokeWidth="2">
                      <polygon points="23 7 16 12 23 17 23 7" />
                      <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                    </svg>
                  </div>
                )}

                {s.kind === 'video' && (
                  <div
                    style={{
                      position: 'absolute',
                      top: '4px',
                      right: '4px',
                      backgroundColor: 'rgba(0,0,0,0.75)',
                      borderRadius: '4px',
                      padding: '1px 5px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '3px'
                    }}
                  >
                    <span style={{ fontSize: '8px', fontWeight: 700, color: '#fff' }}>VIDEO</span>
                  </div>
                )}

                <div
                  style={{
                    position: 'absolute',
                    bottom: 0,
                    left: 0,
                    right: 0,
                    backgroundColor: 'rgba(11, 13, 17, 0.82)',
                    padding: '3px 6px',
                    fontSize: '10px',
                    color: '#ffffff',
                    fontFamily: 'var(--font-mono)',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    textAlign: 'left'
                  }}
                >
                  {s.name}
                </div>
              </button>
            );
          })}
        </div>

        {/* Main Canvas Drawing Feed */}
        <div
          ref={feedRef}
          onMouseDown={handleCanvasMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => {
            setCrosshairPos(null);
            handleMouseUp();
          }}
          style={{
            position: 'relative',
            width: '100%',
            aspectRatio: '16/9',
            backgroundColor: '#07090c',
            borderRadius: '16px',
            overflow: 'hidden',
            border: '1px solid var(--line)',
            boxShadow: 'var(--shadow-lg)',
            cursor: 'crosshair',
            userSelect: 'none'
          }}
        >
          {/* Background image or mock camera graphic */}
          {currentSource.img ? (
            <img
              src={currentSource.img}
              alt="Source Feed"
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                pointerEvents: 'none'
              }}
            />
          ) : (
            <div
              style={{
                width: '100%',
                height: '100%',
                background: `radial-gradient(ellipse at center, ${currentSource.tint || '#1d3246'} 0%, #080b0f 75%)`,
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                pointerEvents: 'none'
              }}
            />
          )}

          <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(5, 8, 12, 0.1)', pointerEvents: 'none' }} />

          {/* Feed Badge */}
          <div
            className="glass-panel"
            style={{
              position: 'absolute',
              left: '12px',
              top: '12px',
              color: 'var(--ink)',
              fontSize: '10.5px',
              padding: '4px 10px',
              borderRadius: '6px',
              fontFamily: 'var(--font-mono)',
              pointerEvents: 'none',
              zIndex: 10
            }}
          >
            {currentSource.name} {isVideo ? `· khung ${vidTicks[vidFrameIdx].label}` : ''}
          </div>

          {/* Crosshair Guide Lines */}
          {crosshairPos && (
            <>
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  right: 0,
                  top: `${crosshairPos.y}%`,
                  height: '1px',
                  borderTop: '1px dashed rgba(255, 255, 255, 0.4)',
                  pointerEvents: 'none',
                  zIndex: 6
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  top: 0,
                  bottom: 0,
                  left: `${crosshairPos.x}%`,
                  width: '1px',
                  borderLeft: '1px dashed rgba(255, 255, 255, 0.4)',
                  pointerEvents: 'none',
                  zIndex: 6
                }}
              />
            </>
          )}

          {/* Visible Bounding Boxes with Move & 4-Corner Resize Handles */}
          {visibleBoxes.map((b) => {
            const labelObj = objLabels.find((o) => o.id === b.labelId);
            const labelName = labelObj ? labelObj.name : 'Unknown';
            const color = labelObj?.tint || getLabelColor(b.labelId);
            const isSelected = selectedSampleId === b.id;

            return (
              <div
                key={b.id}
                onMouseDown={(e) => handleSampleMouseDown(e, b)}
                style={{
                  position: 'absolute',
                  left: `${b.x}%`,
                  top: `${b.y}%`,
                  width: `${b.w}%`,
                  height: `${b.h}%`,
                  border: `${isSelected ? '2.4px' : '1.8px'} solid ${color}`,
                  backgroundColor: `${color}${isSelected ? '38' : '18'}`,
                  boxSizing: 'border-box',
                  cursor: isSelected ? 'move' : 'pointer',
                  boxShadow: isSelected ? `0 0 16px ${color}66, inset 0 0 10px ${color}22` : 'none',
                  zIndex: isSelected ? 15 : 8
                }}
                title={isSelected ? 'Kéo để di chuyển vị trí, hoặc kéo 4 góc để co giãn kích thước' : 'Bấm để chọn khung mẫu'}
              >
                {/* Tag Header with Name & Quick Delete */}
                <div
                  style={{
                    position: 'absolute',
                    left: '-1px',
                    top: '-24px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    backgroundColor: color,
                    color: '#ffffff',
                    fontSize: '9.5px',
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: '4px 4px 0 0',
                    whiteSpace: 'nowrap',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.4)',
                    pointerEvents: isSelected ? 'auto' : 'none'
                  }}
                  onMouseDown={(e) => e.stopPropagation()}
                >
                  <span>{labelName.toUpperCase()}</span>
                  {isSelected && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSample(b.id);
                        setSelectedSampleId(null);
                      }}
                      title="Xóa khung mẫu này"
                      style={{
                        background: 'rgba(0,0,0,0.25)',
                        border: 'none',
                        color: '#ffffff',
                        cursor: 'pointer',
                        borderRadius: '3px',
                        padding: '1px 4px',
                        fontSize: '9px',
                        fontWeight: 700,
                        marginLeft: '4px'
                      }}
                    >
                      ✕
                    </button>
                  )}
                </div>

                {/* 4 Corner Resize Handles when Selected */}
                {isSelected && (
                  <>
                    {/* Top-Left Handle */}
                    <div
                      onMouseDown={(e) => handleResizeMouseDown(e, b, 'resize-tl')}
                      style={{
                        position: 'absolute',
                        left: '-5px',
                        top: '-5px',
                        width: '10px',
                        height: '10px',
                        backgroundColor: '#ffffff',
                        border: `2px solid ${color}`,
                        borderRadius: '2px',
                        cursor: 'nwse-resize',
                        zIndex: 20
                      }}
                    />
                    {/* Top-Right Handle */}
                    <div
                      onMouseDown={(e) => handleResizeMouseDown(e, b, 'resize-tr')}
                      style={{
                        position: 'absolute',
                        right: '-5px',
                        top: '-5px',
                        width: '10px',
                        height: '10px',
                        backgroundColor: '#ffffff',
                        border: `2px solid ${color}`,
                        borderRadius: '2px',
                        cursor: 'nesw-resize',
                        zIndex: 20
                      }}
                    />
                    {/* Bottom-Left Handle */}
                    <div
                      onMouseDown={(e) => handleResizeMouseDown(e, b, 'resize-bl')}
                      style={{
                        position: 'absolute',
                        left: '-5px',
                        bottom: '-5px',
                        width: '10px',
                        height: '10px',
                        backgroundColor: '#ffffff',
                        border: `2px solid ${color}`,
                        borderRadius: '2px',
                        cursor: 'nesw-resize',
                        zIndex: 20
                      }}
                    />
                    {/* Bottom-Right Handle */}
                    <div
                      onMouseDown={(e) => handleResizeMouseDown(e, b, 'resize-br')}
                      style={{
                        position: 'absolute',
                        right: '-5px',
                        bottom: '-5px',
                        width: '10px',
                        height: '10px',
                        backgroundColor: '#ffffff',
                        border: `2px solid ${color}`,
                        borderRadius: '2px',
                        cursor: 'nwse-resize',
                        zIndex: 20
                      }}
                    />
                  </>
                )}
              </div>
            );
          })}

          {/* Draft Bounding Box while dragging to draw */}
          {draftBox && (
            <div
              style={{
                position: 'absolute',
                left: `${draftBox.x}%`,
                top: `${draftBox.y}%`,
                width: `${draftBox.w}%`,
                height: `${draftBox.h}%`,
                border: '2px dashed var(--acc)',
                backgroundColor: 'var(--accq)',
                pointerEvents: 'none',
                zIndex: 10
              }}
            />
          )}
        </div>

        {/* Video Scrubber Timeline if video source */}
        {isVideo && (
          <div
            className="glass-card"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              marginTop: '12px',
              borderRadius: '12px',
              padding: '10px 16px'
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="var(--ink2)">
              <path d="M8 5v14l11-7z" />
            </svg>
            <span style={{ fontSize: '11px', color: 'var(--ink3)', fontFamily: 'var(--font-mono)' }}>00:00</span>
            <div style={{ flex: 1, height: '6px', borderRadius: '3px', backgroundColor: 'var(--raise)', position: 'relative' }}>
              {vidTicks.map((tick, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setVidFrameIdx(i);
                    setSelectedSampleId(null);
                  }}
                  title={`Khung hình ${tick.label}`}
                  style={{
                    position: 'absolute',
                    left: tick.pct,
                    top: '50%',
                    width: '14px',
                    height: '14px',
                    margin: '-7px 0 0 -7px',
                    borderRadius: '50%',
                    border: '2px solid #ffffff',
                    backgroundColor: vidFrameIdx === i ? 'var(--acc)' : 'var(--ink3)',
                    cursor: 'pointer',
                    padding: 0
                  }}
                />
              ))}
            </div>
            <span style={{ fontSize: '11px', color: 'var(--ink3)', fontFamily: 'var(--font-mono)' }}>02:30</span>
            <span style={{ fontSize: '11.5px', color: 'var(--ink)' }}>
              khung <b style={{ color: 'var(--acc)' }}>{vidTicks[vidFrameIdx].label}</b>
            </span>
          </div>
        )}

        {/* Selected Sample Quick Action Toolbar */}
        {selectedSample && (
          <div
            className="glass-panel animate-msg"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              marginTop: '12px',
              borderRadius: '12px',
              padding: '10px 16px',
              border: '1px solid var(--acc)',
              flexWrap: 'wrap'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--acc)' }}>
                Đang chọn mẫu:
              </span>
              <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--ink2)', backgroundColor: 'var(--raise)', padding: '2px 6px', borderRadius: '4px' }}>
                X:{selectedSample.x}% Y:{selectedSample.y}% W:{selectedSample.w}% H:{selectedSample.h}%
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '11.5px', color: 'var(--ink3)' }}>Đổi nhãn:</span>
              <select
                value={selectedSample.labelId}
                onChange={(e) => onUpdateSample(selectedSample.id, { labelId: e.target.value })}
                style={{
                  border: '1px solid var(--line2)',
                  borderRadius: '8px',
                  padding: '5px 10px',
                  backgroundColor: 'var(--bg)',
                  color: 'var(--ink)',
                  fontSize: '12px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  outline: 'none'
                }}
              >
                {objLabels.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </div>

            <div style={{ flex: 1 }} />

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '11px', color: 'var(--ink3)' }}>Kéo thân để dời · Kéo góc để co giãn</span>
              <button
                onClick={() => {
                  onDeleteSample(selectedSample.id);
                  setSelectedSampleId(null);
                }}
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  padding: '5px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--p0)',
                  backgroundColor: 'transparent',
                  color: 'var(--p0)',
                  cursor: 'pointer'
                }}
              >
                Xóa mẫu (Del)
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Right Column: Label Management List & Action Bar */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {/* Label Management Card */}
        <div
          className="glass-panel"
          style={{
            borderRadius: '16px',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: 'var(--shadow-md)'
          }}
        >
          {/* Header with Title & + Thêm nhãn mới button */}
          <div
            style={{
              padding: '14px 18px',
              borderBottom: '1px solid var(--line)',
              backgroundColor: 'var(--panel)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '10px'
            }}
          >
            <div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span>Danh mục Nhãn đối tượng</span>
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
                  {objLabels.length} nhãn
                </span>
              </div>
              <div style={{ fontSize: '11px', color: 'var(--ink3)', marginTop: '2px' }}>
                Bấm nhãn để chọn gắn mẫu (Phím 1-{objLabels.length})
              </div>
            </div>

            {/* + Thêm nhãn mới Button */}
            <button
              onClick={handleOpenAddModal}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                padding: '6px 13px',
                borderRadius: '8px',
                border: 'none',
                backgroundColor: 'var(--acc)',
                color: '#ffffff',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                boxShadow: '0 2px 8px var(--acc-glow)',
                whiteSpace: 'nowrap'
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              <span>Thêm nhãn</span>
            </button>
          </div>

          {/* List of Labels with Edit & Delete Actions */}
          <div style={{ maxHeight: '420px', overflowY: 'auto', padding: '6px' }}>
            {objLabels.map((o, idx) => {
              const isSelected = selectedLabelId === o.id;
              const isNguoi = o.kind === 'nguoi';
              const labelTint = o.tint || getLabelColor(o.id);

              return (
                <div
                  key={o.id}
                  onClick={() => setSelectedLabelId(o.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '10px 14px',
                    borderRadius: '10px',
                    marginBottom: '4px',
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'var(--card-hover)' : 'transparent',
                    border: isSelected ? `1.5px solid ${labelTint}` : '1.5px solid transparent',
                    boxShadow: isSelected ? `0 2px 10px -2px ${labelTint}44` : 'none',
                    transition: 'all 0.16s ease'
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--raise)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                    {/* Number key pill */}
                    <span
                      style={{
                        width: '22px',
                        height: '22px',
                        borderRadius: '7px',
                        backgroundColor: labelTint,
                        color: '#ffffff',
                        fontSize: '11px',
                        fontWeight: 700,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flex: 'none',
                        fontFamily: 'var(--font-mono)',
                        boxShadow: isSelected ? `0 0 10px ${labelTint}66` : 'none'
                      }}
                    >
                      {idx + 1}
                    </span>

                    {/* Label Name & Category Tag */}
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {o.name}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
                        <span
                          style={{
                            fontSize: '9.5px',
                            fontWeight: 600,
                            padding: '1px 6px',
                            borderRadius: '4px',
                            backgroundColor: isNguoi ? 'var(--purpleq)' : 'var(--accq)',
                            color: isNguoi ? 'var(--purple)' : 'var(--acc)'
                          }}
                        >
                          {isNguoi ? 'Người' : 'Xe'}
                        </span>
                        <span style={{ fontSize: '10.5px', color: 'var(--ink3)', fontFamily: 'var(--font-mono)' }}>
                          {o.samples} mẫu
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Actions: Edit & Delete */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flex: 'none' }}>
                    {/* Edit Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleOpenEditModal(o);
                      }}
                      title="Chỉnh sửa tên, loại hoặc màu nhãn"
                      style={{
                        padding: '5px 8px',
                        borderRadius: '6px',
                        border: '1px solid var(--line2)',
                        backgroundColor: 'var(--card)',
                        color: 'var(--ink2)',
                        fontSize: '11px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '3px'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = 'var(--acc)';
                        e.currentTarget.style.color = 'var(--acc)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = 'var(--line2)';
                        e.currentTarget.style.color = 'var(--ink2)';
                      }}
                    >
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                        <path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                      </svg>
                      <span>Sửa</span>
                    </button>

                    {/* Delete Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (window.confirm(`Bạn có chắc muốn xóa nhãn "${o.name}"?`)) {
                          onDeleteLabel(o.id);
                          if (selectedLabelId === o.id) {
                            const next = objLabels.find((x) => x.id !== o.id);
                            if (next) setSelectedLabelId(next.id);
                          }
                        }
                      }}
                      title="Xóa nhãn này"
                      style={{
                        padding: '5px 8px',
                        borderRadius: '6px',
                        border: '1px solid var(--p0q)',
                        backgroundColor: 'var(--p0q)',
                        color: 'var(--p0)',
                        fontSize: '11px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '3px'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--p0)';
                        e.currentTarget.style.color = '#ffffff';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--p0q)';
                        e.currentTarget.style.color = 'var(--p0)';
                      }}
                    >
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      </svg>
                      <span>Xóa</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Footer Save Training Samples Bar */}
          <div
            style={{
              padding: '14px 18px',
              borderTop: '1px solid var(--line)',
              backgroundColor: 'var(--panel)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '10px'
            }}
          >
            <div>
              <div style={{ fontSize: '11.5px', color: 'var(--ink2)', fontWeight: 600 }}>
                Mẫu mới trong phiên: <b style={{ color: 'var(--acc)' }}>{pendingSessionCount}</b>
              </div>
              {savedSuccessMsg && (
                <div style={{ fontSize: '11px', color: 'var(--ok)', marginTop: '2px', fontWeight: 600 }}>
                  {savedSuccessMsg}
                </div>
              )}
            </div>

            <button
              onClick={handleSave}
              disabled={pendingSessionCount === 0}
              style={{
                padding: '8px 18px',
                borderRadius: '9px',
                border: 'none',
                backgroundColor: pendingSessionCount > 0 ? 'var(--ok)' : 'var(--raise)',
                color: pendingSessionCount > 0 ? '#ffffff' : 'var(--ink3)',
                fontSize: '12.5px',
                fontWeight: 700,
                cursor: pendingSessionCount > 0 ? 'pointer' : 'not-allowed',
                boxShadow: pendingSessionCount > 0 ? '0 2px 10px var(--ok-glow)' : 'none',
                transition: 'all 0.16s ease'
              }}
            >
              Lưu {pendingSessionCount > 0 ? `(${pendingSessionCount})` : ''} mẫu
            </button>
          </div>
        </div>
      </div>

      {/* Modal: Thêm / Sửa Nhãn Đối Tượng */}
      {labelModalOpen && (
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
            padding: '20px'
          }}
          onClick={() => setLabelModalOpen(false)}
        >
          <div
            className="glass-panel animate-modal"
            style={{
              width: '100%',
              maxWidth: '440px',
              borderRadius: '16px',
              backgroundColor: 'var(--card)',
              border: '1px solid var(--line2)',
              boxShadow: 'var(--shadow-lg)',
              overflow: 'hidden'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--line)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                backgroundColor: 'var(--panel)'
              }}
            >
              <div style={{ fontSize: '14.5px', fontWeight: 700, color: 'var(--ink)' }}>
                {editingLabel ? `Chỉnh sửa nhãn: ${editingLabel.name}` : 'Thêm nhãn đối tượng mới'}
              </div>
              <button
                onClick={() => setLabelModalOpen(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--ink3)',
                  fontSize: '16px',
                  cursor: 'pointer',
                  padding: '4px'
                }}
              >
                ✕
              </button>
            </div>

            {/* Modal Form Content */}
            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Field 1: Tên nhãn */}
              <div>
                <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink2)', display: 'block', marginBottom: '6px' }}>
                  Tên nhãn đối tượng:
                </label>
                <input
                  value={modalName}
                  onChange={(e) => setModalName(e.target.value)}
                  placeholder="vd: Xe nâng reach stacker, Người mặc áo phản quang…"
                  autoFocus
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    borderRadius: '9px',
                    border: '1px solid var(--line2)',
                    backgroundColor: 'var(--bg)',
                    color: 'var(--ink)',
                    fontSize: '13px',
                    outline: 'none'
                  }}
                />
              </div>

              {/* Field 2: Loại đối tượng */}
              <div>
                <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink2)', display: 'block', marginBottom: '6px' }}>
                  Phân loại đối tượng:
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                  <button
                    onClick={() => setModalKind('xe')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      padding: '8px',
                      borderRadius: '9px',
                      border: modalKind === 'xe' ? '2px solid var(--acc)' : '1px solid var(--line2)',
                      backgroundColor: modalKind === 'xe' ? 'var(--accq)' : 'var(--raise)',
                      color: modalKind === 'xe' ? 'var(--acc)' : 'var(--ink2)',
                      fontWeight: 600,
                      fontSize: '12.5px',
                      cursor: 'pointer'
                    }}
                  >
                    <span>🚗</span>
                    <span>Phương tiện</span>
                  </button>

                  <button
                    onClick={() => setModalKind('nguoi')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      padding: '8px',
                      borderRadius: '9px',
                      border: modalKind === 'nguoi' ? '2px solid var(--purple)' : '1px solid var(--line2)',
                      backgroundColor: modalKind === 'nguoi' ? 'var(--purpleq)' : 'var(--raise)',
                      color: modalKind === 'nguoi' ? 'var(--purple)' : 'var(--ink2)',
                      fontWeight: 600,
                      fontSize: '12.5px',
                      cursor: 'pointer'
                    }}
                  >
                    <span>🚶</span>
                    <span>Người</span>
                  </button>
                </div>
              </div>

              {/* Field 3: Màu sắc nhận diện */}
              <div>
                <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink2)', display: 'block', marginBottom: '8px' }}>
                  Màu sắc nhận diện bounding box:
                </label>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {colorPalette.map((c) => {
                    const isSelected = modalTint === c;
                    return (
                      <button
                        key={c}
                        onClick={() => setModalTint(c)}
                        style={{
                          width: '32px',
                          height: '32px',
                          borderRadius: '8px',
                          backgroundColor: c,
                          border: isSelected ? '3px solid #ffffff' : '2px solid transparent',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#ffffff',
                          boxShadow: isSelected ? `0 0 10px ${c}` : 'none'
                        }}
                      >
                        {isSelected && (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div
              style={{
                padding: '14px 20px',
                borderTop: '1px solid var(--line)',
                backgroundColor: 'var(--panel)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: '10px'
              }}
            >
              <button
                onClick={() => setLabelModalOpen(false)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '8px',
                  border: '1px solid var(--line2)',
                  backgroundColor: 'transparent',
                  color: 'var(--ink2)',
                  fontSize: '12.5px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                Hủy
              </button>

              <button
                onClick={handleSaveLabelModal}
                disabled={!modalName.trim()}
                style={{
                  padding: '8px 20px',
                  borderRadius: '8px',
                  border: 'none',
                  backgroundColor: modalName.trim() ? 'var(--acc)' : 'var(--raise)',
                  color: modalName.trim() ? '#ffffff' : 'var(--ink3)',
                  fontSize: '12.5px',
                  fontWeight: 700,
                  cursor: modalName.trim() ? 'pointer' : 'not-allowed',
                  boxShadow: modalName.trim() ? '0 2px 8px var(--acc-glow)' : 'none'
                }}
              >
                {editingLabel ? 'Cập nhật' : 'Thêm nhãn'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
