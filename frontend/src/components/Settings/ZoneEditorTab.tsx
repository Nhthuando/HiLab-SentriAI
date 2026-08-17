import React, { useState, useRef, useCallback, useEffect } from 'react';
import type { PolygonZone, ObjectLabel } from '../../types';

interface ZoneEditorTabProps {
  clock: string;
  zonesByCam: Record<string, PolygonZone[]>;
  objLabels: ObjectLabel[];
  onUpdateZone: (camId: string, zoneId: string, patch: Partial<PolygonZone>) => void;
  onAddZone: (camId: string, newZone: PolygonZone) => void;
  onDeleteZone: (camId: string, zoneId: string) => void;
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
  onDeleteZone
}) => {
  const [camSel, setCamSel] = useState<'BAI-KIEM' | 'GATE-01'>('BAI-KIEM');
  const [tool, setTool] = useState<'select' | 'draw'>('select');
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);

  // Drawing state
  const [draftPoints, setDraftPoints] = useState<[number, number][]>([]);
  const [draftHover, setDraftHover] = useState<[number, number] | null>(null);

  // Undo / Redo History Stack per camera
  const [history, setHistory] = useState<PolygonZone[][]>([zonesByCam[camSel] || []]);
  const [historyIndex, setHistoryIndex] = useState<number>(0);
  const isUndoRedoActionRef = useRef<boolean>(false);

  // Color picker popup for specific zone
  const [colorPickerZoneId, setColorPickerZoneId] = useState<string | null>(null);

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

  const feedRef = useRef<HTMLDivElement>(null);

  const currentZones = zonesByCam[camSel] || [];
  const selectedZone = currentZones.find((z) => z.id === selectedZoneId) || null;

  // Sync history when switching camera
  useEffect(() => {
    setHistory([zonesByCam[camSel] || []]);
    setHistoryIndex(0);
    setSelectedZoneId(null);
    setDraftPoints([]);
    setDraftHover(null);
    setColorPickerZoneId(null);
  }, [camSel]);

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

  // Undo action
  const handleUndo = useCallback(() => {
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
    }
  }, [tool, draftPoints, historyIndex, history, currentZones, camSel, onUpdateZone, onAddZone, onDeleteZone]);

  // Redo action
  const handleRedo = useCallback(() => {
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
    }
  }, [historyIndex, history, currentZones, camSel, onUpdateZone, onAddZone, onDeleteZone]);

  // Keyboard shortcut listener for Ctrl+Z & Ctrl+Y / Ctrl+Shift+Z
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      } else if (
        (e.ctrlKey || e.metaKey) &&
        (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))
      ) {
        e.preventDefault();
        handleRedo();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleUndo, handleRedo]);

  // Convert mouse event to percentage (0 - 100)
  const getPercentageCoords = useCallback((e: React.MouseEvent): [number, number] | null => {
    if (!feedRef.current) return null;
    const rect = feedRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
    const y = Math.max(0, Math.min(100, ((e.clientY - rect.top) / rect.height) * 100));
    return [+x.toFixed(1), +y.toFixed(1)];
  }, []);

  // Complete zone drawing
  const handleFinishDraw = useCallback(() => {
    if (draftPoints.length < 3) return;
    const newId = 'z' + Date.now();
    const newColor = PRESET_COLORS[currentZones.length % PRESET_COLORS.length];

    const defaultTypes: Record<string, number> = {};
    objLabels.forEach((l) => {
      defaultTypes[l.name] = l.name === 'Container' || l.name === 'Xe nâng' || l.name === 'Xe tải' ? 1 : 0;
    });

    const newZone: PolygonZone = {
      id: newId,
      name: `Zone mới ${currentZones.length + 1}`,
      color: newColor,
      points: draftPoints,
      types: defaultTypes
    };

    const nextState = [...currentZones, newZone];
    onAddZone(camSel, newZone);
    pushHistory(nextState);

    setSelectedZoneId(newId);
    setTool('select');
    setDraftPoints([]);
    setDraftHover(null);
  }, [draftPoints, currentZones, objLabels, camSel, onAddZone, pushHistory]);

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
      if (e.target === feedRef.current || (e.target as HTMLElement).tagName === 'svg') {
        setSelectedZoneId(null);
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

    if (drag.mode === 'vertex' && drag.idx !== undefined) {
      const zone = currentZones.find((z) => z.id === drag.zoneId);
      if (!zone) return;
      const newPoints = zone.points.map((pt, i) => (i === drag.idx ? p : pt));
      onUpdateZone(camSel, drag.zoneId, { points: newPoints });
    } else if (drag.mode === 'move') {
      const dx = p[0] - drag.startX;
      const dy = p[1] - drag.startY;

      const minX = Math.min(...drag.origPoints.map((pt) => pt[0]));
      const maxX = Math.max(...drag.origPoints.map((pt) => pt[0]));
      const minY = Math.min(...drag.origPoints.map((pt) => pt[1]));
      const maxY = Math.max(...drag.origPoints.map((pt) => pt[1]));

      const clampedDx = Math.max(1 - minX, Math.min(99 - maxX, dx));
      const clampedDy = Math.max(1 - minY, Math.min(99 - maxY, dy));

      const newPoints = drag.origPoints.map(([x, y]) => [
        +Math.max(0, Math.min(100, x + clampedDx)).toFixed(1),
        +Math.max(0, Math.min(100, y + clampedDy)).toFixed(1)
      ]) as [number, number][];

      onUpdateZone(camSel, drag.zoneId, { points: newPoints });
    }
  };

  const handleFeedMouseUp = () => {
    if (dragRef.current && dragRef.current.hasMoved) {
      pushHistory(currentZones);
    }
    dragRef.current = null;
  };

  const handleUpdateZoneProp = (zoneId: string, patch: Partial<PolygonZone>) => {
    onUpdateZone(camSel, zoneId, patch);
    const nextState = currentZones.map((z) => (z.id === zoneId ? { ...z, ...patch } : z));
    pushHistory(nextState);
  };

  const handleDeleteZoneWithHistory = (zoneId: string) => {
    onDeleteZone(camSel, zoneId);
    const nextState = currentZones.filter((z) => z.id !== zoneId);
    pushHistory(nextState);
    if (selectedZoneId === zoneId) setSelectedZoneId(null);
  };

  const canUndo = (tool === 'draw' && draftPoints.length > 0) || historyIndex > 0;
  const canRedo = historyIndex < history.length - 1;

  return (
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
          {/* Camera Picker */}
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
              onClick={() => setCamSel('BAI-KIEM')}
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 14px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
                backgroundColor: camSel === 'BAI-KIEM' ? 'var(--acc)' : 'transparent',
                color: camSel === 'BAI-KIEM' ? '#fff' : 'var(--ink2)'
              }}
            >
              Bãi Kiểm
            </button>
            <button
              onClick={() => setCamSel('GATE-01')}
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 14px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
                backgroundColor: camSel === 'GATE-01' ? 'var(--acc)' : 'transparent',
                color: camSel === 'GATE-01' ? '#fff' : 'var(--ink2)'
              }}
            >
              Cổng vào
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
              onClick={() => {
                setTool('draw');
                setSelectedZoneId(null);
              }}
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 14px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
                backgroundColor: tool === 'draw' ? 'var(--acc)' : 'transparent',
                color: tool === 'draw' ? '#fff' : 'var(--ink2)'
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
              disabled={!canUndo}
              title="Hoàn tác (Ctrl+Z)"
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 10px',
                borderRadius: '8px',
                border: 'none',
                cursor: canUndo ? 'pointer' : 'not-allowed',
                backgroundColor: 'transparent',
                color: canUndo ? 'var(--ink)' : 'var(--ink3)',
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
              disabled={!canRedo}
              title="Làm lại (Ctrl+Y)"
              style={{
                fontSize: '12px',
                fontWeight: 600,
                padding: '6px 10px',
                borderRadius: '8px',
                border: 'none',
                cursor: canRedo ? 'pointer' : 'not-allowed',
                backgroundColor: 'transparent',
                color: canRedo ? 'var(--ink)' : 'var(--ink3)',
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
                boxShadow: '0 2px 8px rgba(16, 185, 129, 0.4)'
              }}
            >
              ✓ Hoàn tất zone ({draftPoints.length} điểm)
            </button>
          )}

          {tool === 'draw' && draftPoints.length > 0 && (
            <button
              onClick={() => {
                setDraftPoints([]);
                setDraftHover(null);
              }}
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
          {/* Feed Background Image */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              backgroundImage: `url('${camSel === 'GATE-01' ? '/assets/cam-gate.png' : '/assets/cam-baikiem.png'}')`,
              backgroundSize: 'cover',
              backgroundPosition: 'center',
              pointerEvents: 'none'
            }}
          />
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
            {camSel} · {camSel === 'GATE-01' ? 'Cổng vào' : 'Bãi Kiểm'}
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
            {clock} · Trình chỉnh sửa Zone AI
          </div>

          {/* SVG Polygons and Draft */}
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
            {currentZones.map((z) => {
              const isSelected = selectedZoneId === z.id;
              const pointsStr = z.points.map((p) => `${p[0]},${p[1]}`).join(' ');

              return (
                <polygon
                  key={z.id}
                  points={pointsStr}
                  fill={`${z.color}${isSelected ? '38' : '16'}`}
                  stroke={z.color}
                  strokeWidth={isSelected ? '2.4' : '1.6'}
                  strokeDasharray={isSelected ? '0' : '6 4'}
                  vectorEffect="non-scaling-stroke"
                  style={{
                    cursor: tool === 'select' ? (isSelected ? 'move' : 'pointer') : 'crosshair',
                    pointerEvents: 'auto'
                  }}
                  onMouseDown={(e) => {
                    if (tool !== 'select') return;
                    e.stopPropagation();
                    const p = getPercentageCoords(e);
                    if (!p) return;
                    setSelectedZoneId(z.id);
                    dragRef.current = {
                      mode: 'move',
                      zoneId: z.id,
                      startX: p[0],
                      startY: p[1],
                      origPoints: z.points.map((pt) => [...pt]),
                      hasMoved: false
                    };
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
          {currentZones.map((z) => {
            const topPoint = z.points.reduce((prev, curr) => (curr[1] < prev[1] ? curr : prev), z.points[0]);
            return (
              <span
                key={`lbl-${z.id}`}
                style={{
                  position: 'absolute',
                  left: `${topPoint[0]}%`,
                  top: `${topPoint[1]}%`,
                  transform: 'translateY(-115%)',
                  backgroundColor: z.color,
                  color: '#ffffff',
                  fontSize: '9.5px',
                  fontWeight: 700,
                  padding: '2px 8px',
                  borderRadius: '4px',
                  whiteSpace: 'nowrap',
                  pointerEvents: 'none',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.5)'
                }}
              >
                {z.name}
              </span>
            );
          })}

          {/* Handles for Selected Zone in Select Mode */}
          {tool === 'select' && selectedZone && (
            <>
              {/* Vertex Handles */}
              {selectedZone.points.map((p, i) => (
                <span
                  key={`v-${i}`}
                  onMouseDown={(e) => {
                    e.stopPropagation();
                    const coords = getPercentageCoords(e);
                    if (!coords) return;
                    dragRef.current = {
                      mode: 'vertex',
                      zoneId: selectedZone.id,
                      idx: i,
                      startX: coords[0],
                      startY: coords[1],
                      origPoints: selectedZone.points.map((pt) => [...pt]),
                      hasMoved: false
                    };
                  }}
                  title="Kéo góc để sửa hình dạng"
                  style={{
                    position: 'absolute',
                    left: `${p[0]}%`,
                    top: `${p[1]}%`,
                    width: '13px',
                    height: '13px',
                    margin: '-6.5px 0 0 -6.5px',
                    backgroundColor: '#ffffff',
                    border: `2px solid ${selectedZone.color}`,
                    borderRadius: '3px',
                    cursor: 'grab',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.6)',
                    zIndex: 10
                  }}
                />
              ))}

              {/* Edge Midpoint Handles */}
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

                      const newPoints = [...selectedZone.points];
                      newPoints.splice(i + 1, 0, [+midX.toFixed(1), +midY.toFixed(1)]);
                      onUpdateZone(camSel, selectedZone.id, { points: newPoints });

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

        {/* Helper Hint */}
        <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--ink3)', display: 'flex', gap: '16px', padding: '0 4px' }}>
          <span>⌨️ Phím tắt: <b>Ctrl+Z</b> Hoàn tác, <b>Ctrl+Y</b> Làm lại</span>
          <span>•</span>
          <span>{tool === 'draw' ? 'Bấm vào góc đầu để đóng đa giác' : 'Kéo góc để nắn hình, kéo điểm giữa cạnh để thêm góc'}</span>
        </div>
      </div>

      {/* Right: Zone Cards & Type Permission Matrix */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {currentZones.map((z) => {
          const isSelected = selectedZoneId === z.id;
          const isColorPickerOpen = colorPickerZoneId === z.id;

          return (
            <div
              key={z.id}
              onClick={() => setSelectedZoneId(z.id)}
              className="glass-card"
              style={{
                borderRadius: '16px',
                padding: '16px',
                cursor: 'pointer',
                border: isSelected ? `2px solid ${z.color}` : '1px solid var(--line)',
                boxShadow: isSelected ? `0 0 20px ${z.color}33` : 'var(--shadow-md)',
                transition: 'all 0.18s ease'
              }}
            >
              {/* Card Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                {/* Color Swatch */}
                <div style={{ position: 'relative' }}>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setColorPickerZoneId(isColorPickerOpen ? null : z.id);
                    }}
                    title="Bấm để đổi màu sắc zone"
                    style={{
                      width: '26px',
                      height: '26px',
                      borderRadius: '8px',
                      backgroundColor: z.color,
                      border: '2px solid rgba(255,255,255,0.4)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: '0 1px 4px rgba(0,0,0,0.3)'
                    }}
                  >
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="#ffffff">
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
                        top: '32px',
                        borderRadius: '12px',
                        padding: '10px',
                        display: 'grid',
                        gridTemplateColumns: 'repeat(5, 1fr)',
                        gap: '6px',
                        zIndex: 40,
                        boxShadow: 'var(--shadow-lg)',
                        width: '165px'
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
                            width: '24px',
                            height: '24px',
                            borderRadius: '6px',
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
                          width: '24px',
                          height: '24px',
                          borderRadius: '6px',
                          backgroundColor: 'var(--raise)',
                          border: '1px solid var(--line2)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          cursor: 'pointer'
                        }}
                      >
                        <span style={{ fontSize: '11px', color: 'var(--ink)' }}>+</span>
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
                  value={z.name}
                  onChange={(e) => handleUpdateZoneProp(z.id, { name: e.target.value })}
                  onClick={(e) => e.stopPropagation()}
                  placeholder="Tên zone…"
                  style={{
                    flex: 1,
                    minWidth: 0,
                    backgroundColor: 'transparent',
                    border: '1px solid transparent',
                    borderRadius: '8px',
                    padding: '4px 8px',
                    color: '#ffffff',
                    fontSize: '13.5px',
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
                  }}
                />

                {/* Delete Zone Button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteZoneWithHistory(z.id);
                  }}
                  style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    padding: '4px 10px',
                    borderRadius: '7px',
                    border: '1px solid var(--p0)',
                    backgroundColor: 'transparent',
                    color: 'var(--p0)',
                    cursor: 'pointer',
                    fontFamily: 'inherit'
                  }}
                >
                  Xóa
                </button>
              </div>

              <div style={{ fontSize: '11px', color: 'var(--ink3)', marginBottom: '10px' }}>
                Phân quyền loại đối tượng vào zone (bấm để đổi ✓ được phép / ✕ cấm):
              </div>

              {/* Vehicle Permissions Matrix */}
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {objLabels.map((obj) => {
                  const isAllowed = !!z.types[obj.name];
                  return (
                    <button
                      key={obj.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleUpdateZoneProp(z.id, {
                          types: {
                            ...z.types,
                            [obj.name]: isAllowed ? 0 : 1
                          }
                        });
                      }}
                      title={`Bấm để ${isAllowed ? 'cấm' : 'cho phép'} ${obj.name}`}
                      style={{
                        fontSize: '11.5px',
                        fontWeight: 600,
                        padding: '5px 12px',
                        borderRadius: '20px',
                        border: `1px solid ${isAllowed ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`,
                        backgroundColor: isAllowed ? 'var(--okq)' : 'var(--p0q)',
                        color: isAllowed ? 'var(--ok)' : 'var(--p0)',
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        transition: 'all 0.15s ease'
                      }}
                    >
                      {isAllowed ? `✓ ${obj.name}` : `✕ ${obj.name}`}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}

        <div style={{ fontSize: '11.5px', color: 'var(--ink3)', lineHeight: 1.55, padding: '0 4px' }}>
          Phương tiện mang nhãn <b style={{ color: 'var(--p0)' }}>Xe lạ</b> hoặc sai loại được phép sẽ tự động kích hoạt cảnh
          báo vi phạm khi đi vào zone.
        </div>
      </div>
    </div>
  );
};
