import React, { useState, useRef, useCallback, useEffect } from 'react';
import type { ObjectLabel, AnnotationSource, AnnotationSample } from '../../types';

interface ObjectLabelTabProps {
  objLabels: ObjectLabel[];
  annSources: AnnotationSource[];
  annSamples: AnnotationSample[];
  onAddLabel: (name: string, kind: 'xe' | 'nguoi') => void;
  onRenameLabel: (id: string, newName: string) => void;
  onDeleteLabel: (id: string) => void;
  onAddSample: (sample: Omit<AnnotationSample, 'id'>) => void;
  onUpdateSample: (id: string, patch: Partial<AnnotationSample>) => void;
  onDeleteSample: (id: string) => void;
  onSaveSamples: () => void;
}

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

  // New label form
  const [newLabelName, setNewLabelName] = useState<string>('');
  const [newLabelKind, setNewLabelKind] = useState<'xe' | 'nguoi'>('xe');

  // Draft box drawing
  const [draftBox, setDraftBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const dragRef = useRef<{ startX: number; startY: number } | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);

  const [savedSuccessMsg, setSavedSuccessMsg] = useState<string>('');

  const currentSource = annSources.find((s) => s.id === activeSourceId) || annSources[0];
  const isVideo = currentSource.kind === 'video';
  const selectedLabel = objLabels.find((l) => l.id === selectedLabelId);

  const labelColors: Record<string, string> = {
    l1: '#06b6d4',
    l2: '#10b981',
    l3: '#f59e0b',
    l4: '#a855f7',
    l5: '#3b82f6',
    l6: '#f43f5e',
    l7: '#9ca3af',
    l8: '#3b82f6'
  };

  const getLabelColor = (labelId: string) => labelColors[labelId] || '#3b82f6';

  const vidTicks = [
    { label: '00:12', pct: '8%' },
    { label: '00:47', pct: '31%' },
    { label: '01:23', pct: '55%' },
    { label: '02:05', pct: '82%' }
  ];

  // Number key shortcuts (1 - 8) for instant class switching
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
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
  }, [objLabels]);

  const getPercentageCoords = useCallback((e: React.MouseEvent): { x: number; y: number } | null => {
    if (!feedRef.current) return null;
    const rect = feedRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
    const y = Math.max(0, Math.min(100, ((e.clientY - rect.top) / rect.height) * 100));
    return { x: +x.toFixed(1), y: +y.toFixed(1) };
  }, []);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (!selectedLabelId) return;
    const p = getPercentageCoords(e);
    if (!p) return;
    dragRef.current = { startX: p.x, startY: p.y };
    setDraftBox({ x: p.x, y: p.y, w: 0, h: 0 });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    const p = getPercentageCoords(e);
    if (!p) return;
    setCrosshairPos(p);

    if (!dragRef.current) return;

    const startX = dragRef.current.startX;
    const startY = dragRef.current.startY;
    const x = Math.min(startX, p.x);
    const y = Math.min(startY, p.y);
    const w = Math.abs(p.x - startX);
    const h = Math.abs(p.y - startY);

    setDraftBox({ x, y, w, h });
  };

  const handleMouseUp = () => {
    if (!dragRef.current || !draftBox) {
      dragRef.current = null;
      setDraftBox(null);
      return;
    }
    dragRef.current = null;

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
    setDraftBox(null);
  };

  const pendingSessionCount = annSamples.filter((s) => s.session === 1).length;

  const handleSave = () => {
    if (pendingSessionCount === 0) return;
    onSaveSamples();
    setSavedSuccessMsg(`✓ Đã lưu thành công ${pendingSessionCount} mẫu gắn nhãn!`);
  };

  // Filter boxes for current source and frame
  const visibleBoxes = annSamples.filter((s) => {
    if (s.srcId !== currentSource.id) return false;
    if (isVideo && s.frame !== vidFrameIdx) return false;
    return true;
  });

  const selectedSample = annSamples.find((s) => s.id === selectedSampleId) || null;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.58fr) minmax(360px, 1fr)',
        gap: '18px',
        alignItems: 'start'
      }}
    >
      {/* Left: Feed, Sources, Video Timeline & Drawing */}
      <div>
        {/* Source Media Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '13.5px', fontWeight: 700, color: '#ffffff' }}>Gắn mẫu từ hình / video</span>
          <span style={{ fontSize: '12px', color: 'var(--ink3)' }}>
            {selectedLabel
              ? `Đang chọn: "${selectedLabel.name}". Phím 1-${objLabels.length} để đổi nhanh nhãn.`
              : 'Chọn một nhãn ở bảng bên phải trước.'}
          </span>
          <div style={{ flex: 1 }} />
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
                  backgroundColor: '#07090c',
                  cursor: 'pointer',
                  overflow: 'hidden',
                  padding: 0,
                  boxShadow: isSel ? '0 0 14px var(--acc-glow)' : 'none'
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    backgroundImage: s.img ? `url('${s.img}')` : 'none',
                    background: s.img ? undefined : `linear-gradient(150deg, ${s.tint || '#1a2129'}, #0c0f13)`,
                    backgroundSize: 'cover',
                    backgroundPosition: 'center'
                  }}
                />
                {s.kind === 'video' && (
                  <span
                    style={{
                      position: 'absolute',
                      left: '5px',
                      top: '5px',
                      backgroundColor: 'rgba(0,0,0,0.75)',
                      borderRadius: '4px',
                      padding: '1px 5px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '3px'
                    }}
                  >
                    <svg width="8" height="8" viewBox="0 0 24 24" fill="#fff">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                    <span style={{ fontSize: '8px', fontWeight: 700, color: '#fff' }}>VIDEO</span>
                  </span>
                )}
                <span
                  style={{
                    position: 'absolute',
                    left: 0,
                    right: 0,
                    bottom: 0,
                    backgroundColor: 'rgba(0,0,0,0.75)',
                    color: '#ffffff',
                    fontSize: '9.5px',
                    fontWeight: 600,
                    padding: '3px 6px',
                    textAlign: 'left',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis'
                  }}
                >
                  {s.name}
                </span>
              </button>
            );
          })}
        </div>

        {/* Interactive Annotation Feed */}
        <div
          ref={feedRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => {
            handleMouseUp();
            setCrosshairPos(null);
          }}
          style={{
            position: 'relative',
            width: '100%',
            aspectRatio: '16/9',
            backgroundColor: '#07090c',
            border: '1px solid var(--line2)',
            borderRadius: '16px',
            overflow: 'hidden',
            cursor: selectedLabelId ? 'crosshair' : 'default',
            userSelect: 'none',
            boxShadow: 'var(--shadow-lg)'
          }}
        >
          {/* Feed Background Image */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              backgroundImage: currentSource.img ? `url('${currentSource.img}')` : 'none',
              background: currentSource.img ? undefined : `linear-gradient(150deg, ${currentSource.tint || '#1a2129'}, #0c0f13)`,
              backgroundSize: 'cover',
              backgroundPosition: 'center',
              pointerEvents: 'none'
            }}
          />
          <div style={{ position: 'absolute', inset: 0, backgroundColor: 'rgba(5, 8, 12, 0.1)', pointerEvents: 'none' }} />

          {/* Feed Badge */}
          <div
            className="glass-panel"
            style={{
              position: 'absolute',
              left: '12px',
              top: '12px',
              color: '#ffffff',
              fontSize: '10.5px',
              padding: '4px 10px',
              borderRadius: '6px',
              fontFamily: 'var(--font-mono)',
              pointerEvents: 'none'
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

          {/* Visible Bounding Boxes */}
          {visibleBoxes.map((b) => {
            const labelObj = objLabels.find((o) => o.id === b.labelId);
            const labelName = labelObj ? labelObj.name : 'Unknown';
            const color = getLabelColor(b.labelId);
            const isSelected = selectedSampleId === b.id;

            return (
              <div
                key={b.id}
                onMouseDown={(e) => {
                  e.stopPropagation();
                  setSelectedSampleId(b.id);
                }}
                style={{
                  position: 'absolute',
                  left: `${b.x}%`,
                  top: `${b.y}%`,
                  width: `${b.w}%`,
                  height: `${b.h}%`,
                  border: `${isSelected ? '2.4px' : '1.8px'} solid ${color}`,
                  backgroundColor: `${color}${isSelected ? '38' : '18'}`,
                  boxSizing: 'border-box',
                  cursor: 'pointer',
                  zIndex: 8
                }}
              >
                <span
                  style={{
                    position: 'absolute',
                    left: '-1px',
                    top: '-20px',
                    backgroundColor: color,
                    color: '#000000',
                    fontSize: '9.5px',
                    fontWeight: 700,
                    padding: '1.5px 7px',
                    borderRadius: '3px',
                    whiteSpace: 'nowrap',
                    pointerEvents: 'none',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.5)'
                  }}
                >
                  {labelName.toUpperCase()}
                </span>
              </div>
            );
          })}

          {/* Draft Bounding Box while dragging */}
          {draftBox && (
            <div
              style={{
                position: 'absolute',
                left: `${draftBox.x}%`,
                top: `${draftBox.y}%`,
                width: `${draftBox.w}%`,
                height: `${draftBox.h}%`,
                border: '1.8px dashed #ffffff',
                backgroundColor: 'rgba(255, 255, 255, 0.2)',
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

        {/* Selected Sample Edit Panel */}
        {selectedSample && (
          <div
            className="glass-panel"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              marginTop: '12px',
              borderRadius: '12px',
              padding: '10px 16px',
              border: '1px solid var(--acc)'
            }}
          >
            <span style={{ fontSize: '12.5px', fontWeight: 600, color: '#ffffff' }}>Mẫu đang chọn:</span>
            <select
              value={selectedSample.labelId}
              onChange={(e) => onUpdateSample(selectedSample.id, { labelId: e.target.value })}
              style={{
                border: '1px solid var(--line2)',
                borderRadius: '8px',
                padding: '6px 10px',
                backgroundColor: 'var(--bg)',
                color: 'var(--ink)',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer'
              }}
            >
              {objLabels.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
            <button
              onClick={() => {
                onDeleteSample(selectedSample.id);
                setSelectedSampleId(null);
              }}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '6px 12px',
                borderRadius: '8px',
                border: '1px solid var(--p0)',
                backgroundColor: 'transparent',
                color: 'var(--p0)',
                cursor: 'pointer'
              }}
            >
              Xóa mẫu
            </button>
            <button
              onClick={() => setSelectedSampleId(null)}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '6px 12px',
                borderRadius: '8px',
                border: '1px solid var(--line2)',
                backgroundColor: 'transparent',
                color: 'var(--ink2)',
                cursor: 'pointer'
              }}
            >
              Bỏ chọn
            </button>
          </div>
        )}

        {/* Save Samples Button */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginTop: '14px' }}>
          <button
            onClick={handleSave}
            disabled={pendingSessionCount === 0}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '13px',
              fontWeight: 600,
              padding: '10px 20px',
              borderRadius: '11px',
              border: 'none',
              backgroundColor: pendingSessionCount > 0 ? 'var(--ok)' : 'var(--raise)',
              color: pendingSessionCount > 0 ? '#fff' : 'var(--ink3)',
              cursor: pendingSessionCount > 0 ? 'pointer' : 'not-allowed',
              fontFamily: 'inherit',
              boxShadow: pendingSessionCount > 0 ? '0 2px 10px rgba(16, 185, 129, 0.4)' : 'none'
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <path d="M20 6 9 17l-5-5" />
            </svg>
            Lưu {pendingSessionCount} mẫu đã gắn
          </button>
          <span style={{ fontSize: '11.5px', color: 'var(--ink3)', flex: 1 }}>
            Khoanh khung quanh đối tượng theo nhãn đang chọn, có thể gắn nhiều mẫu trên một khung hình rồi bấm lưu.
          </span>
        </div>

        {/* Success Banner */}
        {savedSuccessMsg && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              marginTop: '12px',
              backgroundColor: 'var(--okq)',
              border: '1px solid var(--ok)',
              borderRadius: '12px',
              padding: '10px 16px',
              flexWrap: 'wrap'
            }}
          >
            <span style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--ok)' }}>{savedSuccessMsg}</span>
            {isVideo && (
              <button
                onClick={() => setVidFrameIdx((prev) => (prev + 1) % vidTicks.length)}
                style={{
                  fontSize: '11.5px',
                  fontWeight: 600,
                  padding: '6px 14px',
                  borderRadius: '8px',
                  border: '1px solid var(--line2)',
                  backgroundColor: 'var(--card)',
                  color: 'var(--ink)',
                  cursor: 'pointer'
                }}
              >
                Khung tiếp theo →
              </button>
            )}
            <button
              onClick={() => setSavedSuccessMsg('')}
              style={{
                fontSize: '11.5px',
                fontWeight: 600,
                padding: '6px 14px',
                borderRadius: '8px',
                border: 'none',
                backgroundColor: 'transparent',
                color: 'var(--ink3)',
                cursor: 'pointer'
              }}
            >
              Đóng
            </button>
          </div>
        )}
      </div>

      {/* Right: Label Selection List & Add New Label Form */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Label Selector List */}
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
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--line)', backgroundColor: 'rgba(26, 30, 39, 0.6)' }}>
            <div style={{ fontSize: '13.5px', fontWeight: 700, color: '#ffffff' }}>Chọn nhãn để gắn mẫu</div>
            <div style={{ fontSize: '11.5px', color: 'var(--ink3)', marginTop: '2px' }}>
              {selectedLabel
                ? `Đang chọn: ${selectedLabel.name} (Phím tắt: 1-${objLabels.length})`
                : 'Bấm một nhãn để bắt đầu'}
            </div>
          </div>

          <div style={{ maxHeight: '320px', overflowY: 'auto' }}>
            {objLabels.map((o, idx) => {
              const isSelected = selectedLabelId === o.id;
              const isNguoi = o.kind === 'nguoi';

              return (
                <div
                  key={o.id}
                  onClick={() => setSelectedLabelId(o.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '10px 16px',
                    borderBottom: '1px solid var(--line)',
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'var(--accq)' : 'transparent',
                    borderLeft: isSelected ? '3px solid var(--acc)' : '3px solid transparent',
                    transition: 'background-color 0.15s ease'
                  }}
                >
                  {/* Keyboard Shortcut Badge */}
                  <span
                    style={{
                      fontSize: '10px',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
                      padding: '2px 6px',
                      borderRadius: '5px',
                      backgroundColor: isSelected ? 'var(--acc)' : 'var(--raise)',
                      color: isSelected ? '#ffffff' : 'var(--ink3)'
                    }}
                  >
                    {idx + 1}
                  </span>

                  <div
                    style={{
                      width: '34px',
                      height: '26px',
                      flex: 'none',
                      borderRadius: '6px',
                      background: `linear-gradient(150deg, ${o.tint}, #0d1017)`,
                      border: `1px solid ${isSelected ? 'var(--acc)' : 'var(--line2)'}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#cfd6dd" strokeWidth="1.8">
                      {isNguoi ? (
                        <path d="M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM5 21c0-4 3-6 7-6s7 2 7 6" />
                      ) : (
                        <path d="M3 16V9h11v7M14 11h4l3 3v2M6 19a1.5 1.5 0 1 0 0-3M17 19a1.5 1.5 0 1 0 0-3" />
                      )}
                    </svg>
                  </div>

                  <input
                    value={o.name}
                    onChange={(e) => onRenameLabel(o.id, e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      flex: 1,
                      minWidth: 0,
                      border: 'none',
                      backgroundColor: 'transparent',
                      color: '#ffffff',
                      fontSize: '13px',
                      fontWeight: 600,
                      outline: 'none'
                    }}
                  />

                  <span
                    style={{
                      fontSize: '10px',
                      fontWeight: 600,
                      padding: '2px 8px',
                      borderRadius: '12px',
                      backgroundColor: isNguoi ? 'var(--accq)' : 'var(--okq)',
                      color: isNguoi ? 'var(--acc)' : 'var(--ok)',
                      flex: 'none'
                    }}
                  >
                    {isNguoi ? 'Người' : 'Xe'}
                  </span>

                  <span
                    style={{
                      fontSize: '11px',
                      color: 'var(--ink3)',
                      fontFamily: 'var(--font-mono)',
                      flex: 'none',
                      width: '48px',
                      textAlign: 'right'
                    }}
                  >
                    {o.samples} mẫu
                  </span>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteLabel(o.id);
                      if (selectedLabelId === o.id) setSelectedLabelId('');
                    }}
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      padding: '3px 8px',
                      borderRadius: '6px',
                      border: '1px solid var(--p0)',
                      backgroundColor: 'transparent',
                      color: 'var(--p0)',
                      cursor: 'pointer',
                      flex: 'none'
                    }}
                  >
                    Xóa
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {/* Add New Label Card */}
        <div
          className="glass-panel"
          style={{
            borderRadius: '16px',
            padding: '18px',
            boxShadow: 'var(--shadow-md)',
            border: '1px solid var(--line2)'
          }}
        >
          <div style={{ fontSize: '14px', fontWeight: 700, color: '#ffffff', marginBottom: '4px' }}>
            Thêm nhãn đối tượng mới
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--ink3)', lineHeight: 1.5, marginBottom: '14px' }}>
            Đặt tên nhãn tiếng Việt (vd: Xe nâng reach stacker, Người mặc áo phản quang…) để dùng cho cấu hình các zone.
          </div>

          <label style={{ fontSize: '11.5px', fontWeight: 600, color: 'var(--ink2)', display: 'block', marginBottom: '6px' }}>
            Tên nhãn
          </label>
          <input
            value={newLabelName}
            onChange={(e) => setNewLabelName(e.target.value)}
            placeholder="vd: Người mặc áo phản quang"
            style={{
              width: '100%',
              border: '1px solid var(--line2)',
              borderRadius: '9px',
              padding: '9px 12px',
              backgroundColor: 'var(--bg)',
              color: 'var(--ink)',
              fontSize: '13px',
              outline: 'none',
              marginBottom: '13px'
            }}
          />

          <label style={{ fontSize: '11.5px', fontWeight: 600, color: 'var(--ink2)', display: 'block', marginBottom: '8px' }}>
            Loại đối tượng
          </label>
          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            <button
              onClick={() => setNewLabelKind('nguoi')}
              style={{
                flex: 1,
                fontSize: '12px',
                fontWeight: 600,
                padding: '8px',
                borderRadius: '9px',
                border: `1px solid ${newLabelKind === 'nguoi' ? 'var(--acc)' : 'var(--line2)'}`,
                backgroundColor: newLabelKind === 'nguoi' ? 'var(--acc)' : 'transparent',
                color: newLabelKind === 'nguoi' ? '#fff' : 'var(--ink2)',
                cursor: 'pointer'
              }}
            >
              Người
            </button>
            <button
              onClick={() => setNewLabelKind('xe')}
              style={{
                flex: 1,
                fontSize: '12px',
                fontWeight: 600,
                padding: '8px',
                borderRadius: '9px',
                border: `1px solid ${newLabelKind === 'xe' ? 'var(--acc)' : 'var(--line2)'}`,
                backgroundColor: newLabelKind === 'xe' ? 'var(--acc)' : 'transparent',
                color: newLabelKind === 'xe' ? '#fff' : 'var(--ink2)',
                cursor: 'pointer'
              }}
            >
              Hình dáng xe
            </button>
          </div>

          <button
            onClick={() => {
              if (!newLabelName.trim()) return;
              onAddLabel(newLabelName.trim(), newLabelKind);
              setNewLabelName('');
            }}
            style={{
              width: '100%',
              padding: '11px',
              borderRadius: '10px',
              border: 'none',
              background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
              color: '#ffffff',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              boxShadow: '0 2px 8px rgba(59, 130, 246, 0.4)'
            }}
          >
            Lưu nhãn
          </button>
        </div>
      </div>
    </div>
  );
};
