import React, { useState, useEffect, useRef } from 'react';
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
  FloatingNotification
} from './types';
import {
  INITIAL_VEHICLES,
  INITIAL_LABELS,
  INITIAL_GATE_EVENTS,
  INITIAL_ZONES,
  INITIAL_OBJ_LABELS,
  INITIAL_ANN_SOURCES,
  INITIAL_ANN_SAMPLES,
  INITIAL_QA_MESSAGES,
  QA_KNOWLEDGE_BASE,
  QA_FALLBACK
} from './mockData';

import { Header } from './components/Header';
import { GateMonitor } from './components/GateMonitor';
import { AreaMonitor } from './components/AreaMonitor';
import { VehicleLabelTab } from './components/Settings/VehicleLabelTab';
import { ZoneEditorTab } from './components/Settings/ZoneEditorTab';
import { ObjectLabelTab } from './components/Settings/ObjectLabelTab';
import { ThemeSettingsTab } from './components/Settings/ThemeSettingsTab';
import { AIQAChat } from './components/AIQAChat';
import { FloatingAlert } from './components/FloatingAlert';
import { useBroadcastChannel, useWebSocket } from './hooks';

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
  const [vehicles] = useState(INITIAL_VEHICLES);
  const [labels, setLabels] = useState<Record<string, 'quen' | 'la'>>(INITIAL_LABELS);
  const [gateEvents] = useState(INITIAL_GATE_EVENTS);
  const [zonesByCam, setZonesByCam] = useState<Record<string, PolygonZone[]>>(INITIAL_ZONES);
  const [objLabels, setObjLabels] = useState<ObjectLabel[]>(INITIAL_OBJ_LABELS);
  const [annSources] = useState<AnnotationSource[]>(INITIAL_ANN_SOURCES);
  const [annSamples, setAnnSamples] = useState<AnnotationSample[]>(INITIAL_ANN_SAMPLES);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(INITIAL_QA_MESSAGES);

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

  // Toggle vehicle status
  const handleToggleLabel = (plate: string) => {
    setLabels((prev) => ({
      ...prev,
      [plate]: prev[plate] === 'la' ? 'quen' : 'la'
    }));
  };

  // Zone handlers
  const handleUpdateZone = (camId: string, zoneId: string, patch: Partial<PolygonZone>) => {
    setZonesByCam((prev) => {
      const list = prev[camId] || [];
      const updated = list.map((z) => (z.id === zoneId ? { ...z, ...patch } : z));
      return { ...prev, [camId]: updated };
    });
  };

  const handleAddZone = (camId: string, newZone: PolygonZone) => {
    setZonesByCam((prev) => ({
      ...prev,
      [camId]: [...(prev[camId] || []), newZone]
    }));
  };

  const handleDeleteZone = (camId: string, zoneId: string) => {
    setZonesByCam((prev) => ({
      ...prev,
      [camId]: (prev[camId] || []).filter((z) => z.id !== zoneId)
    }));
  };

  // Object label handlers
  const handleAddLabel = (name: string, kind: 'xe' | 'nguoi', tint?: string) => {
    const tints = ['#3b82f6', '#10b981', '#06b6d4', '#a855f7', '#f59e0b', '#f43f5e', '#8b5cf6', '#64748b'];
    const newLabel: ObjectLabel = {
      id: 'l' + Date.now(),
      name,
      kind,
      tint: tint || tints[objLabels.length % tints.length],
      samples: 0
    };
    setObjLabels((prev) => [...prev, newLabel]);
  };

  const handleRenameLabel = (id: string, newName: string, kind?: 'xe' | 'nguoi', tint?: string) => {
    setObjLabels((prev) =>
      prev.map((l) =>
        l.id === id
          ? {
              ...l,
              name: newName,
              ...(kind ? { kind } : {}),
              ...(tint ? { tint } : {})
            }
          : l
      )
    );
  };

  const handleDeleteLabel = (id: string) => {
    setObjLabels((prev) => prev.filter((l) => l.id !== id));
    setAnnSamples((prev) => prev.filter((s) => s.labelId !== id));
  };

  // Annotation sample handlers
  const handleAddSample = (sample: Omit<AnnotationSample, 'id'>) => {
    const newSample: AnnotationSample = {
      ...sample,
      id: 's' + Date.now()
    };
    setAnnSamples((prev) => [...prev, newSample]);
  };

  const handleUpdateSample = (id: string, patch: Partial<AnnotationSample>) => {
    setAnnSamples((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  };

  const handleDeleteSample = (id: string) => {
    setAnnSamples((prev) => prev.filter((s) => s.id !== id));
  };

  const handleSaveSamples = () => {
    const counts: Record<string, number> = {};
    annSamples.forEach((s) => {
      if (s.session === 1) {
        counts[s.labelId] = (counts[s.labelId] || 0) + 1;
      }
    });

    setObjLabels((prev) =>
      prev.map((l) => (counts[l.id] ? { ...l, samples: l.samples + counts[l.id] } : l))
    );

    setAnnSamples((prev) => prev.map((s) => ({ ...s, session: 0 })));
  };

  // Chat Q&A handler
  const handleSendMessage = (text: string) => {
    const userMsg: ChatMessage = {
      id: 'user-' + Date.now(),
      role: 'user',
      text,
      timestamp: clockStr
    };

    const queryLower = text.toLowerCase();
    const match = QA_KNOWLEDGE_BASE.find((item) =>
      item.keys.some((k) => queryLower.includes(k))
    ) || QA_FALLBACK;

    const aiMsg: ChatMessage = {
      id: 'ai-' + Date.now(),
      role: 'ai',
      text: match.text,
      clip: match.clip,
      timestamp: clockStr
    };

    setChatMessages((prev) => [...prev, userMsg, aiMsg]);
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
            clock={clockStr}
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
              />
            )}

            {/* Sub-tab 3: Nhãn đối tượng */}
            {settingsSubTab === 'obj' && (
              <ObjectLabelTab
                objLabels={objLabels}
                annSources={annSources}
                annSamples={annSamples}
                onAddLabel={handleAddLabel}
                onRenameLabel={handleRenameLabel}
                onDeleteLabel={handleDeleteLabel}
                onAddSample={handleAddSample}
                onUpdateSample={handleUpdateSample}
                onDeleteSample={handleDeleteSample}
                onSaveSamples={handleSaveSamples}
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
          </div>
        )}

        {/* Tab 4: Hỏi đáp AI */}
        {activeTab === 'qa' && (
          <AIQAChat
            messages={chatMessages}
            onSendMessage={handleSendMessage}
            onClearChat={() => setChatMessages(INITIAL_QA_MESSAGES)}
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
