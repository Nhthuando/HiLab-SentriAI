import React from 'react';
import type { TabId } from '../types';

interface HeaderProps {
  activeTab: TabId;
  onSelectTab: (tab: TabId) => void;
  clock: string;
}

export const Header: React.FC<HeaderProps> = ({ activeTab, onSelectTab, clock }) => {
  const tabs: { id: TabId; label: string; icon: React.ReactNode }[] = [
    {
      id: 'mon',
      label: 'Giám sát cổng',
      icon: (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
          <circle cx="12" cy="13" r="4" />
        </svg>
      )
    },
    {
      id: 'area',
      label: 'Giám sát khu vực',
      icon: (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>
      )
    },
    {
      id: 'set',
      label: 'Cài đặt hệ thống',
      icon: (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      )
    },
    {
      id: 'qa',
      label: 'Hỏi đáp AI',
      icon: (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z" />
        </svg>
      )
    }
  ];

  return (
    <header
      className="glass-panel"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '18px',
        padding: '12px 24px',
        borderBottom: '1px solid var(--line)',
        position: 'sticky',
        top: 0,
        zIndex: 50,
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)'
      }}
    >
      {/* Brand Logo & Title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div
          style={{
            width: '36px',
            height: '36px',
            flex: 'none',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 10px rgba(59, 130, 246, 0.35)'
          }}
        >
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2.2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <circle cx="12" cy="11" r="3" />
          </svg>
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '15px', fontWeight: 700, letterSpacing: '-0.02em', color: '#ffffff' }}>
              SentriAI
            </span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--ink3)', marginTop: '1px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span>Giám sát camera AI & Nhận diện biển số</span>
          </div>
        </div>
      </div>

      <div style={{ flex: 1 }} />

      {/* Navigation Tabs */}
      <nav
        aria-label="Chuyển đổi phân hệ"
        style={{
          display: 'flex',
          backgroundColor: 'rgba(15, 18, 23, 0.85)',
          border: '1px solid var(--line)',
          borderRadius: '12px',
          padding: '4px',
          gap: '4px',
          boxShadow: 'inset 0 1px 3px rgba(0, 0, 0, 0.4)'
        }}
      >
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onSelectTab(tab.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '7px',
                fontSize: '12.5px',
                fontWeight: 600,
                padding: '7px 16px',
                borderRadius: '9px',
                border: isActive ? '1px solid rgba(59, 130, 246, 0.35)' : '1px solid transparent',
                cursor: 'pointer',
                fontFamily: 'inherit',
                backgroundColor: isActive ? 'var(--acc)' : 'transparent',
                color: isActive ? '#ffffff' : 'var(--ink2)',
                boxShadow: isActive ? '0 2px 10px rgba(59, 130, 246, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.2)' : 'none',
                transition: 'all 0.18s cubic-bezier(0.16, 1, 0.3, 1)'
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = 'var(--raise)';
                  e.currentTarget.style.color = 'var(--ink)';
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = 'transparent';
                  e.currentTarget.style.color = 'var(--ink2)';
                }
              }}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Right Live Status & Clock */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          paddingLeft: '6px'
        }}
      >
        {/* System Online Status */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            backgroundColor: 'var(--okq)',
            border: '1px solid rgba(16, 185, 129, 0.25)',
            padding: '5px 11px',
            borderRadius: '20px',
            fontSize: '11px',
            fontWeight: 600,
            color: 'var(--ok)'
          }}
        >
          <span
            className="animate-live-green"
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              backgroundColor: 'var(--ok)'
            }}
          />
          <span>2 Cam Online</span>
        </div>

        {/* Live Clock */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            backgroundColor: 'var(--card)',
            border: '1px solid var(--line)',
            padding: '5px 12px',
            borderRadius: '9px',
            fontFamily: 'var(--font-mono)',
            fontSize: '11.5px',
            color: 'var(--ink)',
            fontWeight: 600
          }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--ink3)" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <span>{clock}</span>
        </div>
      </div>
    </header>
  );
};
