import React, { useState, useEffect } from 'react';
import type {
  TabId,
  SettingsSubTab,
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
  INITIAL_AREA_EVENTS,
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
import { AIQAChat } from './components/AIQAChat';
import { FloatingAlert } from './components/FloatingAlert';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabId>('mon');
  const [settingsSubTab, setSettingsSubTab] = useState<SettingsSubTab>('label');
  const [now, setNow] = useState<Date>(new Date());

  // Domain states
  const [vehicles] = useState(INITIAL_VEHICLES);
  const [labels, setLabels] = useState<Record<string, 'quen' | 'la'>>(INITIAL_LABELS);
  const [gateEvents] = useState(INITIAL_GATE_EVENTS);
  const [areaEvents] = useState(INITIAL_AREA_EVENTS);
  const [zonesByCam, setZonesByCam] = useState<Record<string, PolygonZone[]>>(INITIAL_ZONES);
  const [objLabels, setObjLabels] = useState<ObjectLabel[]>(INITIAL_OBJ_LABELS);
  const [annSources] = useState<AnnotationSource[]>(INITIAL_ANN_SOURCES);
  const [annSamples, setAnnSamples] = useState<AnnotationSample[]>(INITIAL_ANN_SAMPLES);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(INITIAL_QA_MESSAGES);

  // Floating cross-tab notification
  const [floatingAlert, setFloatingAlert] = useState<FloatingNotification | null>(null);

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
  const handleAddLabel = (name: string, kind: 'xe' | 'nguoi') => {
    const tints = ['#2a4a6b', '#3d5a40', '#5a5230', '#4a3d5a', '#3d5a55'];
    const newLabel: ObjectLabel = {
      id: 'l' + Date.now(),
      name,
      kind,
      tint: tints[objLabels.length % tints.length],
      samples: 0
    };
    setObjLabels((prev) => [...prev, newLabel]);
  };

  const handleRenameLabel = (id: string, newName: string) => {
    setObjLabels((prev) => prev.map((l) => (l.id === id ? { ...l, name: newName } : l)));
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

  // Simulate cross-tab floating alert if user is in Settings or QA
  useEffect(() => {
    if (activeTab === 'set' || activeTab === 'qa') {
      const timer = setTimeout(() => {
        setFloatingAlert({
          id: 'alert-' + Date.now(),
          title: 'CẢNH BÁO VI PHẠM ZONE',
          message: 'Phát hiện Xe máy lạ vừa đi vào Zone cấm phương tiện cá nhân!',
          zone: 'BAI-KIEM · Zone cấm PT cá nhân',
          time: clockStr,
          camId: 'BAI-KIEM'
        });
      }, 7000);
      return () => clearTimeout(timer);
    } else {
      setFloatingAlert(null);
    }
  }, [activeTab, clockStr]);

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
      <Header activeTab={activeTab} onSelectTab={setActiveTab} clock={clockStr} />

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
            zones={zonesByCam['BAI-KIEM'] || []}
            events={areaEvents}
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
                width: 'fit-content'
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
                  boxShadow: settingsSubTab === 'label' ? '0 2px 8px rgba(59, 130, 246, 0.35)' : 'none'
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
                  boxShadow: settingsSubTab === 'zone' ? '0 2px 8px rgba(59, 130, 246, 0.35)' : 'none'
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
                  boxShadow: settingsSubTab === 'obj' ? '0 2px 8px rgba(59, 130, 246, 0.35)' : 'none'
                }}
              >
                Nhãn đối tượng
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
