import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type {
  TabId,
  SettingsSubTab,
  ThemeMode,
  AccentColor,
  PolygonZone,
  ObjectLabel,
  AnnotationSource,
  AnnotationSample,
  ChatMessage,
  FloatingNotification,
  Vehicle,
  GateEvent,
  ObjectKind
} from './types';
import {
  INITIAL_ZONES
} from './mockData';

import { Header } from './components/Header';
import { GateMonitor } from './components/GateMonitor';
import { AreaMonitor } from './components/AreaMonitor';
import { VehicleLabelTab } from './components/Settings/VehicleLabelTab';
import { ZoneEditorTab } from './components/Settings/ZoneEditorTab';
import { ObjectLabelTab } from './components/Settings/ObjectLabelTab';
import { ThemeSettingsTab } from './components/Settings/ThemeSettingsTab';
import { NotificationTab } from './components/Settings/NotificationTab';
import { AIQAChat } from './components/AIQAChat';
import { FloatingAlert } from './components/FloatingAlert';
import { useBroadcastChannel, useWebSocket } from './hooks';
import { useZoneMutations } from './hooks/useZoneMutations';
import {
  getCameraSnapshot,
  getZones,
  zoneRecordToView,
} from './api/zones';
import { getVehicles } from './api/vehicles';
import { askQA } from './api/qa';
import { clearChatHistory, getChatHistory } from './api/chat';
import { ApiError } from './api/client';

const LEGACY_DEMO_SOURCE_IDS = new Set(['src1', 'src2']);

function withoutLegacyDemoSources(sources: AnnotationSource[]): AnnotationSource[] {
  return sources.filter((source) => !(source.isDefault === true && LEGACY_DEMO_SOURCE_IDS.has(source.id)));
}

function isUnsavedAnnotationSource(source: AnnotationSource): boolean {
  return source.id.startsWith('imported-') || Boolean(source.img?.startsWith('data:'));
}

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabId>('mon');
  const [settingsSubTab, setSettingsSubTab] = useState<SettingsSubTab>('label');
  const [now, setNow] = useState<Date>(new Date());

  // Theme & Appearance Preferences
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    return (localStorage.getItem('sentriai_theme') as ThemeMode) || 'dark';
  });
  const [accentColor, setAccentColor] = useState<AccentColor>(() => {
    return (localStorage.getItem('sentriai_accent') as AccentColor) || 'blue';
  });
  const [glassEffect, setGlassEffect] = useState<boolean>(() => {
    return localStorage.getItem('sentriai_glass') !== 'false';
  });
  const [compactMode, setCompactMode] = useState<boolean>(() => {
    return localStorage.getItem('sentriai_compact') === 'true';
  });

  // Domain states
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [labels, setLabels] = useState<Record<string, 'quen' | 'la'>>({});
  const [gateEvents, setGateEvents] = useState<GateEvent[]>([]);
  const [zonesByCam, setZonesByCam] = useState<Record<string, PolygonZone[]>>(() => ({
    'GATE-01': INITIAL_ZONES['GATE-01'] || [],
    'BAI-KIEM': [],
  }));
  const [zoneEditorLoading, setZoneEditorLoading] = useState(true);
  const [zoneEditorError, setZoneEditorError] = useState<string | null>(null);
  const [objectLabelError, setObjectLabelError] = useState<string | null>(null);
  const [objectLabelRegistryStatus, setObjectLabelRegistryStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [areaSnapshotImage, setAreaSnapshotImage] = useState<string | null>(null);
  const [objLabels, setObjLabels] = useState<ObjectLabel[]>([]);
  const [annSources, setAnnSources] = useState<AnnotationSource[]>(() => {
    try {
      const saved = localStorage.getItem('sentriai_user_media_sources');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          const cleaned = withoutLegacyDemoSources(parsed as AnnotationSource[]);
          if (cleaned.length !== parsed.length) {
            localStorage.setItem('sentriai_user_media_sources', JSON.stringify(cleaned));
          }
          return cleaned;
        }
      }
    } catch {}
    return [];
  });
  const [annSamples, setAnnSamples] = useState<AnnotationSample[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isChatHistoryLoading, setIsChatHistoryLoading] = useState(true);
  const [isChatSending, setIsChatSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  const handleUpdateSources = useCallback((updated: AnnotationSource[]) => {
    setAnnSources(updated);
    try {
      localStorage.setItem('sentriai_user_media_sources', JSON.stringify(updated));
    } catch (err) {
      console.warn('Failed to save media sources to localStorage:', err);
    }
  }, []);

  // Floating cross-tab notification
  const [floatingAlert, setFloatingAlert] = useState<FloatingNotification | null>(null);
  const seenAreaAlertIdsRef = useRef(new Set<string>());
  const pendingHiddenAlertRef = useRef<FloatingNotification | null>(null);

  // Synchronize Theme & Preferences to DOM and LocalStorage
  useEffect(() => {
    const root = document.documentElement;

    const applyTheme = (mode: ThemeMode) => {
      let resolvedTheme: 'dark' | 'light' = 'dark';
      if (mode === 'system') {
        resolvedTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      } else {
        resolvedTheme = mode;
      }
      root.setAttribute('data-theme', resolvedTheme);
      localStorage.setItem('sentriai_theme', mode);
    };

    applyTheme(themeMode);

    // If system mode, listen to OS color scheme changes
    if (themeMode === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      const listener = () => applyTheme('system');
      mediaQuery.addEventListener('change', listener);
      return () => mediaQuery.removeEventListener('change', listener);
    }
  }, [themeMode]);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-accent', accentColor);
    localStorage.setItem('sentriai_accent', accentColor);
  }, [accentColor]);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-glass', String(glassEffect));
    localStorage.setItem('sentriai_glass', String(glassEffect));
  }, [glassEffect]);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-compact', String(compactMode));
    localStorage.setItem('sentriai_compact', String(compactMode));
  }, [compactMode]);

  // Quick theme toggle handler
  const handleToggleQuickTheme = () => {
    const currentResolved = document.documentElement.getAttribute('data-theme');
    const nextMode: ThemeMode = currentResolved === 'dark' ? 'light' : 'dark';
    setThemeMode(nextMode);
  };

  // Reset appearance defaults
  const handleResetDefaults = () => {
    setThemeMode('dark');
    setAccentColor('blue');
    setGlassEffect(true);
    setCompactMode(false);
  };

  // Live clock
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Format HH:mm:ss
  const pad = (n: number) => String(n).padStart(2, '0');
  const clockStr = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;

  // Toggle vehicle status with real backend sync
  const handleToggleLabel = async (plate: string) => {
    const currentStatus = labels[plate] || 'la';
    const nextStatus: 'quen' | 'la' = currentStatus === 'la' ? 'quen' : 'la';

    // Optimistic UI update
    setLabels((prev) => ({
      ...prev,
      [plate]: nextStatus
    }));

    setVehicles((prev) =>
      prev.map((v) =>
        v.plate === plate
          ? { ...v, tint: nextStatus === 'quen' ? '#10b981' : '#f43f5e' }
          : v
      )
    );

    // VehicleLabelTab owns the API mutation. This callback keeps the shared
    // Gate label state responsive without sending a duplicate PATCH request.
  };

  useEffect(() => {
    let active = true;
    const refreshVehicles = () => {
      getVehicles()
        .then((records) => {
          if (!active) return;
          setVehicles(records);
          setLabels(Object.fromEntries(records.map((vehicle) => [
            vehicle.plate,
            vehicle.status === 'KNOWN' ? 'quen' : 'la',
          ])));
        })
        .catch(() => {
          if (!active) return;
          setVehicles([]);
          setLabels({});
        });
    };
    refreshVehicles();
    const timer = window.setInterval(refreshVehicles, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const [snapshotImageByCam, setSnapshotImageByCam] = useState<Record<string, string | null>>({
    'BAI-KIEM': null,
    'GATE-01': null,
  });

  const allObjLabelNames = useMemo(
    () => objLabels.map((label) => label.name),
    [objLabels],
  );
  const detectableObjLabelNames = useMemo(
    () => objLabels.filter((label) => label.isDetectable).map((label) => label.name),
    [objLabels],
  );

  const {
    updateZone: handleUpdateZone,
    addZone: handleAddZone,
    deleteZone: handleDeleteZone,
    statusByZoneId: zoneMutationStatusById,
    notice: zoneMutationNotice,
  } = useZoneMutations({
    zonesByCam,
    setZonesByCam,
    allLabelNames: allObjLabelNames,
    detectableLabelNames: detectableObjLabelNames,
    registryReady: objectLabelRegistryStatus === 'ready',
    setEditorError: setZoneEditorError,
  });

  const loadZoneEditorData = useCallback(async () => {
    setZoneEditorLoading(true);
    setZoneEditorError(null);

    try {
      const [baikiemRecords, gateRecords] = await Promise.all([
        getZones('BAI-KIEM').catch(() => []),
        getZones('GATE-01').catch(() => []),
      ]);

      setZonesByCam((prev) => ({
        ...prev,
        'BAI-KIEM': baikiemRecords.map((record) => zoneRecordToView(record, allObjLabelNames)),
        'GATE-01': gateRecords.map((record) => zoneRecordToView(record, allObjLabelNames)),
      }));
    } catch {
      setZoneEditorError('Không thể tải dữ liệu zone. Nhấn để thử lại.');
    } finally {
      setZoneEditorLoading(false);
    }

    try {
      const [baikiemSnap, gateSnap] = await Promise.all([
        getCameraSnapshot('BAI-KIEM').catch(() => null),
        getCameraSnapshot('GATE-01').catch(() => null),
      ]);
      setSnapshotImageByCam({
        'BAI-KIEM': baikiemSnap,
        'GATE-01': gateSnap,
      });
      setAreaSnapshotImage(baikiemSnap);
    } catch {
      setAreaSnapshotImage(null);
    }
  }, [allObjLabelNames]);

  useEffect(() => {
    void loadZoneEditorData();
  }, [loadZoneEditorData]);

  const loadObjectLabels = useCallback(async () => {
    setObjectLabelRegistryStatus('loading');
    try {
      const { getLabels } = await import('./api/labels');
      const data = await getLabels();
      if (!Array.isArray(data)) throw new Error('Phản hồi danh mục nhãn không hợp lệ.');
      setObjLabels(data);
      setObjectLabelError(null);
      setObjectLabelRegistryStatus('ready');
    } catch (err) {
      console.warn('Could not fetch labels from API:', err);
      setObjLabels([]);
      setObjectLabelRegistryStatus('error');
      setObjectLabelError('Không thể tải danh mục nhãn từ máy chủ. Danh mục hiện được để trống để tránh dùng dữ liệu giả.');
    }
  }, []);

  const retryZoneEditorData = useCallback(() => {
    void loadObjectLabels();
    void loadZoneEditorData();
  }, [loadObjectLabels, loadZoneEditorData]);

  // Fetch labels, media sources & samples from API on mount
  useEffect(() => {
    void loadObjectLabels();
    import('./api/labels').then(({ getMediaSources, getAnnotationSamples }) => {

      getMediaSources()
        .then((media) => {
          if (Array.isArray(media)) {
            setAnnSources((prev) => {
              const localDrafts = withoutLegacyDemoSources(prev).filter(isUnsavedAnnotationSource);
              const map = new Map(localDrafts.map((source) => [source.id, source]));
              media.forEach((m) => map.set(m.id, m));
              const merged = Array.from(map.values());
              try {
                localStorage.setItem('sentriai_user_media_sources', JSON.stringify(merged));
              } catch {}
              return merged;
            });
          }
        })
        .catch((err) => console.warn('Could not fetch media sources from API:', err));

      getAnnotationSamples()
        .then((samples) => {
          if (Array.isArray(samples)) {
            setAnnSamples((prev) => {
              const existingIds = new Set(samples.map((s) => s.id));
              const unsavedDrafts = prev.filter((p) => p.session === 1 && !existingIds.has(p.id));
              return [...samples, ...unsavedDrafts];
            });
          }
        })
        .catch((err) => console.warn('Could not fetch samples from API:', err));

    });
  }, [loadObjectLabels]);

  // Object label handlers with API integration
  const handleAddLabel = async (name: string, baseClass: string, kind: ObjectKind, tint?: string) => {
    const tints = ['#3b82f6', '#10b981', '#06b6d4', '#a855f7', '#f59e0b', '#f43f5e', '#8b5cf6', '#64748b'];
    const assignedTint = tint || tints[objLabels.length % tints.length];
    
    try {
      setObjectLabelError(null);
      const { createLabel } = await import('./api/labels');
      const created = await createLabel({
        vietnameseName: name,
        baseClass,
        kind,
        tint: assignedTint,
      });
      setObjLabels((prev) => [...prev, created]);
    } catch (err) {
      console.warn('API error creating label:', err);
      setObjectLabelError(err instanceof Error ? err.message : 'Không thể tạo nhãn trên máy chủ.');
    }
  };

  const handleRenameLabel = async (id: string, newName: string, baseClass?: string, kind?: ObjectKind, tint?: string) => {
    try {
      setObjectLabelError(null);
      const { updateLabel } = await import('./api/labels');
      const updated = await updateLabel(id, { vietnameseName: newName, baseClass, kind, tint });
      setObjLabels((prev) => prev.map((label) => label.id === id ? updated : label));
    } catch (err) {
      console.warn('API error updating label:', err);
      setObjectLabelError(err instanceof Error ? err.message : 'Không thể cập nhật nhãn trên máy chủ.');
    }
  };

  const handleDeleteLabel = async (id: string) => {
    try {
      setObjectLabelError(null);
      const { deleteLabel } = await import('./api/labels');
      await deleteLabel(id);
      setObjLabels((prev) => prev.filter((label) => label.id !== id));
      setAnnSamples((prev) => prev.filter((sample) => sample.labelId !== id));
    } catch (err) {
      console.warn('API error deleting label:', err);
      setObjectLabelError(err instanceof Error ? err.message : 'Không thể xóa nhãn trên máy chủ.');
    }
  };

  // Annotation sample handlers
  const handleAddSample = (sample: Omit<AnnotationSample, 'id'> & { id?: string }) => {
    const newSample: AnnotationSample = {
      ...sample,
      id: sample.id || 's' + Date.now()
    };
    setAnnSamples((prev) => [...prev, newSample]);
  };

  const handleUpdateSample = (id: string, patch: Partial<AnnotationSample>) => {
    setAnnSamples((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  };

  const handleDeleteSample = (id: string) => {
    setAnnSamples((prev) => prev.filter((s) => s.id !== id));
  };

  const handleSaveSamples = async (): Promise<boolean> => {
    const pending = annSamples.filter((s) => s.session === 1);
    if (pending.length > 0) {
      try {
        const { saveAnnotationSamples, getLabels } = await import('./api/labels');
        await saveAnnotationSamples(pending);
        const refreshed = await getLabels();
        if (Array.isArray(refreshed)) {
          setObjLabels(refreshed);
          setObjectLabelError(null);
        }
      } catch (err) {
        console.warn('API error saving samples; keeping annotations for retry:', err);
        return false;
      }
    }

    // Clear saved boxes from active canvas once persisted to database
    setAnnSamples([]);
    return true;
  };

  useEffect(() => {
    let cancelled = false;

    getChatHistory()
      .then((history) => {
        if (cancelled) return;
        setChatMessages(history.map((message) => ({
          id: message.id,
          role: message.role === 'assistant' ? 'ai' : 'user',
          text: message.text,
          timestamp: message.createdAt,
          clip: message.clip,
          evidence: message.evidence,
        })));
        setChatError(null);
      })
      .catch((error) => {
        if (cancelled) return;
        console.warn('Failed to load Q&A chat history:', error);
        setChatError('Không thể tải lịch sử chat, vui lòng thử lại.');
      })
      .finally(() => {
        if (!cancelled) setIsChatHistoryLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const getQaErrorMessage = (error: unknown): string => {
    if (error instanceof ApiError && error.status === 504) {
      return 'AI phản hồi quá chậm, vui lòng thử lại';
    }
    if (error instanceof ApiError && error.status === 503) {
      return 'AI đang không khả dụng, vui lòng thử lại';
    }
    return 'Không thể kết nối Trợ lý AI, vui lòng thử lại';
  };

  // Chat Q&A handlers
  const handleSendMessage = async (text: string) => {
    if (isChatSending) return;
    const userMsg: ChatMessage = {
      id: 'user-' + Date.now(),
      role: 'user',
      text,
      timestamp: new Date().toISOString()
    };

    setChatMessages((prev) => [...prev, userMsg]);
    setChatError(null);
    setIsChatSending(true);
    try {
      const response = await askQA(text);
      setChatMessages((prev) => [...prev, {
        id: response.id,
        role: 'ai',
        text: response.text,
        timestamp: response.createdAt,
        clip: response.clip,
        evidence: response.evidence,
      }]);
    } catch (error) {
      console.warn('Q&A request failed:', error);
      setChatError(getQaErrorMessage(error));
    } finally {
      setIsChatSending(false);
    }
  };

  const handleClearChat = async () => {
    if (isChatSending) return;
    setChatError(null);
    try {
      await clearChatHistory();
      setChatMessages([]);
    } catch (error) {
      console.warn('Failed to clear Q&A chat history:', error);
      setChatError('Không thể xóa lịch sử chat, vui lòng thử lại.');
    }
  };

  const acceptAreaAlert = (notification: FloatingNotification): boolean => {
    if (seenAreaAlertIdsRef.current.has(notification.id)) return false;

    seenAreaAlertIdsRef.current.add(notification.id);
    if (seenAreaAlertIdsRef.current.size > 200) {
      seenAreaAlertIdsRef.current.clear();
      seenAreaAlertIdsRef.current.add(notification.id);
    }

    if (document.hidden && activeTab !== 'area') {
      pendingHiddenAlertRef.current = notification;
    } else if (activeTab !== 'area') {
      setFloatingAlert(notification);
    }
    return true;
  };

  // Cross-tab BroadcastChannel for alert synchronization (BR-08)
  const { postMessage: broadcastAlert } = useBroadcastChannel<FloatingNotification>(
    'sentriai-alerts',
    (incomingAlert) => {
      if (
        incomingAlert &&
        typeof incomingAlert.id === 'string' &&
        incomingAlert.camId === 'BAI-KIEM'
      ) {
        acceptAreaAlert(incomingAlert);
      }
    }
  );

  // Real-time WebSocket /ws/alerts subscription for urgent area violations
  useWebSocket<{
    type: string;
    level: string;
    title: string;
    message: string;
    cameraId?: string;
    timestamp: string;
    data?: Record<string, unknown>;
  }>({
    path: '/ws/alerts',
    onMessage: (msg) => {
      const alertData = msg?.data;
      if (
        !msg ||
        msg.type !== 'alert' ||
        msg.level !== 'critical' ||
        msg.cameraId !== 'BAI-KIEM' ||
        !alertData ||
        typeof alertData.violationId !== 'string' ||
        typeof alertData.zoneName !== 'string' ||
        typeof msg.title !== 'string' ||
        typeof msg.message !== 'string'
      ) return;

      const timestamp = new Date(msg.timestamp);
      if (Number.isNaN(timestamp.getTime())) return;
      const pad = (value: number) => String(value).padStart(2, '0');
      const time = `${pad(timestamp.getHours())}:${pad(timestamp.getMinutes())}:${pad(timestamp.getSeconds())}`;

      const notif: FloatingNotification = {
        id: alertData.violationId,
        title: msg.title,
        message: msg.message,
        zone: `BAI-KIEM · ${alertData.zoneName}`,
        time,
        camId: 'BAI-KIEM',
      };

      if (acceptAreaAlert(notif)) {
        broadcastAlert(notif);
      }
    },
  });

  // Real-time WebSocket /ws/events/gate subscription for newly detected vehicles and gate events
  useWebSocket<{
    type?: string;
    data?: any;
    id?: string;
    plate?: string;
    licensePlate?: string;
    status?: 'quen' | 'la' | 'KNOWN' | 'STRANGER';
    lane?: string;
    zone?: string;
    conf?: number;
    time?: string;
  }>({
    path: '/ws/events/gate',
    onMessage: (msg) => {
      const eventData = msg?.data || msg;
      const plate = eventData?.plate || eventData?.licensePlate;
      if (!plate || plate === '—') return;

      const rawStatus = eventData?.status;
      const status: 'quen' | 'la' = (rawStatus === 'KNOWN' || rawStatus === 'quen') ? 'quen' : 'la';
      const eventId = eventData?.id || `ge-${Date.now()}`;
      const timeStr = eventData?.time || clockStr.slice(0, 5);

      // 1. Prepend to gateEvents
      setGateEvents((prev) => {
        const exists = prev.some((e) => e.id === eventId);
        if (exists) return prev;
        const newEvent: GateEvent = {
          id: eventId,
          time: timeStr,
          plate,
          zone: eventData?.zone || (eventData?.lane === 'IN_2' ? 'Làn IN 2 · Làn phụ' : 'Làn IN 1 · Cổng chính'),
          conf: eventData?.conf || 95,
          status,
        };
        return [newEvent, ...prev.slice(0, 49)];
      });

      // 2. Auto-add to vehicles and labels if not present
      setVehicles((prev) => {
        const existing = prev.find((v) => v.plate === plate);
        if (existing) {
          return prev.map((v) =>
            v.plate === plate
              ? { ...v, visits: (v.visits || 1) + 1, last: 'Vừa xong' }
              : v
          );
        }
        const isContainer = plate.includes('R') || plate.includes('H');
        const isTruck = plate.includes('C');
        const inferredType = isContainer ? 'Container' : isTruck ? 'Xe tải' : 'Xe con';
        const newVehicle: Vehicle = {
          plate,
          type: inferredType,
          visits: 1,
          last: 'Vừa xong',
          tint: status === 'quen' ? '#10b981' : '#f43f5e',
        };
        return [newVehicle, ...prev];
      });

      setLabels((prev) => {
        if (prev[plate]) return prev;
        return { ...prev, [plate]: status };
      });
    },
  });

  // Automatically dismiss floating alert when user navigates to area tab
  useEffect(() => {
    if (activeTab === 'area') {
      setFloatingAlert(null);
      pendingHiddenAlertRef.current = null;
      return;
    }

    const showPendingAlert = () => {
      if (!document.hidden && pendingHiddenAlertRef.current) {
        setFloatingAlert(pendingHiddenAlertRef.current);
        pendingHiddenAlertRef.current = null;
      }
    };

    document.addEventListener('visibilitychange', showPendingAlert);
    showPendingAlert();
    return () => document.removeEventListener('visibilitychange', showPendingAlert);
  }, [activeTab]);

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: 'var(--bg)',
        color: 'var(--ink)',
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      {/* Top Application Header */}
      <Header
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        clock={clockStr}
        themeMode={themeMode}
        onToggleQuickTheme={handleToggleQuickTheme}
      />

      {/* Main Content Area */}
      <main style={{ flex: 1 }}>
        {/* Tab 1: Giám sát cổng */}
        {activeTab === 'mon' && (
          <GateMonitor
            zones={zonesByCam['GATE-01'] || []}
            events={gateEvents}
            labels={labels}
          />
        )}

        {/* Tab 2: Giám sát khu vực */}
        {activeTab === 'area' && (
          <AreaMonitor
            clock={clockStr}
          />
        )}

        {/* Tab 3: Cài đặt */}
        {activeTab === 'set' && (
          <div style={{ padding: '24px', maxWidth: '1420px', margin: '0 auto' }}>
            {/* Settings Sub-tab Switcher */}
            <div
              className="glass-card"
              style={{
                display: 'flex',
                gap: '5px',
                borderRadius: '12px',
                padding: '4px',
                marginBottom: '20px',
                width: 'fit-content',
                flexWrap: 'wrap'
              }}
            >
              <button
                onClick={() => setSettingsSubTab('label')}
                style={{
                  fontSize: '12.5px',
                  fontWeight: 600,
                  padding: '8px 18px',
                  borderRadius: '9px',
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  whiteSpace: 'nowrap',
                  backgroundColor: settingsSubTab === 'label' ? 'var(--acc)' : 'transparent',
                  color: settingsSubTab === 'label' ? '#ffffff' : 'var(--ink2)',
                  boxShadow: settingsSubTab === 'label' ? '0 2px 8px var(--acc-glow)' : 'none'
                }}
              >
                Gắn nhãn xe
              </button>
              <button
                onClick={() => setSettingsSubTab('zone')}
                style={{
                  fontSize: '12.5px',
                  fontWeight: 600,
                  padding: '8px 18px',
                  borderRadius: '9px',
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  whiteSpace: 'nowrap',
                  backgroundColor: settingsSubTab === 'zone' ? 'var(--acc)' : 'transparent',
                  color: settingsSubTab === 'zone' ? '#ffffff' : 'var(--ink2)',
                  boxShadow: settingsSubTab === 'zone' ? '0 2px 8px var(--acc-glow)' : 'none'
                }}
              >
                Vẽ zone
              </button>
              <button
                onClick={() => setSettingsSubTab('obj')}
                style={{
                  fontSize: '12.5px',
                  fontWeight: 600,
                  padding: '8px 18px',
                  borderRadius: '9px',
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  whiteSpace: 'nowrap',
                  backgroundColor: settingsSubTab === 'obj' ? 'var(--acc)' : 'transparent',
                  color: settingsSubTab === 'obj' ? '#ffffff' : 'var(--ink2)',
                  boxShadow: settingsSubTab === 'obj' ? '0 2px 8px var(--acc-glow)' : 'none'
                }}
              >
                Nhãn đối tượng
              </button>
              <button
                onClick={() => setSettingsSubTab('theme')}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '12.5px',
                  fontWeight: 600,
                  padding: '8px 18px',
                  borderRadius: '9px',
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  whiteSpace: 'nowrap',
                  backgroundColor: settingsSubTab === 'theme' ? 'var(--acc)' : 'transparent',
                  color: settingsSubTab === 'theme' ? '#ffffff' : 'var(--ink2)',
                  boxShadow: settingsSubTab === 'theme' ? '0 2px 8px var(--acc-glow)' : 'none'
                }}
              >
                <span>☀️/🌙</span>
                <span>Giao diện & Chủ đề</span>
              </button>
              <button
                onClick={() => setSettingsSubTab('notification')}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '12.5px',
                  fontWeight: 600,
                  padding: '8px 18px',
                  borderRadius: '9px',
                  border: 'none',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  whiteSpace: 'nowrap',
                  backgroundColor: settingsSubTab === 'notification' ? 'var(--acc)' : 'transparent',
                  color: settingsSubTab === 'notification' ? '#ffffff' : 'var(--ink2)',
                  boxShadow: settingsSubTab === 'notification' ? '0 2px 8px var(--acc-glow)' : 'none'
                }}
              >
                <span>🔔</span>
                <span>Thông báo & Cảnh báo</span>
              </button>
            </div>

            {/* Sub-tab 1: Gắn nhãn xe */}
            {settingsSubTab === 'label' && (
              <VehicleLabelTab
                vehicles={vehicles}
                labels={labels}
                onToggleLabel={handleToggleLabel}
              />
            )}

            {/* Sub-tab 2: Vẽ zone */}
            {settingsSubTab === 'zone' && (
              <ZoneEditorTab
                clock={clockStr}
                zonesByCam={zonesByCam}
                objLabels={objLabels}
                onUpdateZone={handleUpdateZone}
                onAddZone={handleAddZone}
                onDeleteZone={handleDeleteZone}
                mutationStatusByZoneId={zoneMutationStatusById}
                mutationNotice={zoneMutationNotice}
                snapshotImageByCam={snapshotImageByCam}
                snapshotImage={areaSnapshotImage}
                isLoading={zoneEditorLoading}
                apiError={zoneEditorError}
                labelRegistryStatus={objectLabelRegistryStatus}
                onRetry={retryZoneEditorData}
              />
            )}

            {/* Sub-tab 3: Nhãn đối tượng */}
            {settingsSubTab === 'obj' && (
              <ObjectLabelTab
                objLabels={objLabels}
                annSources={annSources}
                annSamples={annSamples}
                onUpdateSources={handleUpdateSources}
                onAddLabel={handleAddLabel}
                onRenameLabel={handleRenameLabel}
                onDeleteLabel={handleDeleteLabel}
                onAddSample={handleAddSample}
                onUpdateSample={handleUpdateSample}
                onDeleteSample={handleDeleteSample}
                onSaveSamples={handleSaveSamples}
                apiError={objectLabelError}
              />
            )}

            {/* Sub-tab 4: Giao diện & Chủ đề */}
            {settingsSubTab === 'theme' && (
              <ThemeSettingsTab
                themeMode={themeMode}
                onSelectThemeMode={setThemeMode}
                accentColor={accentColor}
                onSelectAccentColor={setAccentColor}
                glassEffect={glassEffect}
                onToggleGlassEffect={setGlassEffect}
                compactMode={compactMode}
                onToggleCompactMode={setCompactMode}
                onResetDefaults={handleResetDefaults}
              />
            )}

            {/* Sub-tab 5: Cấu hình thông báo Telegram / Email */}
            {settingsSubTab === 'notification' && (
              <NotificationTab />
            )}
          </div>
        )}

        {/* Tab 4: Hỏi đáp AI */}
        {activeTab === 'qa' && (
          <AIQAChat
            messages={chatMessages}
            onSendMessage={handleSendMessage}
            onClearChat={handleClearChat}
            isHistoryLoading={isChatHistoryLoading}
            isSending={isChatSending}
            error={chatError}
          />
        )}
      </main>

      {/* Floating Cross-Tab Alert */}
      <FloatingAlert
        notification={floatingAlert}
        onNavigateToMonitor={(camId) => {
          if (camId === 'GATE-01') setActiveTab('mon');
          else setActiveTab('area');
          setFloatingAlert(null);
        }}
        onDismiss={() => setFloatingAlert(null)}
      />
    </div>
  );
};

export default App;
