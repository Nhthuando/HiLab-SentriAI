import React from 'react';
import type { TabId, ThemeMode } from '../types';

interface HeaderProps {
  activeTab: TabId;
  onSelectTab: (tab: TabId) => void;
  clock: string;
  themeMode?: ThemeMode;
  onToggleQuickTheme?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  onSelectTab,
  clock,
  themeMode = 'dark',
  onToggleQuickTheme
}) => {
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

  const isLight = document.documentElement.getAttribute('data-theme') === 'light' || themeMode === 'light';

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
        boxShadow: 'var(--shadow-md)'
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
            background: 'linear-gradient(135deg, var(--acc) 0%, #1d4ed8 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 10px var(--acc-glow)'
          }}
        >
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2.2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <circle cx="12" cy="11" r="3" />
          </svg>
        </div>

        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '15px', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--ink)' }}>
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
          backgroundColor: 'var(--bg-subtle)',
          border: '1px solid var(--line)',
          borderRadius: '12px',
          padding: '4px',
          gap: '4px',
          boxShadow: 'inset 0 1px 2px rgba(0, 0, 0, 0.15)'
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
                border: isActive ? '1px solid var(--acc-glow)' : '1px solid transparent',
                cursor: 'pointer',
                fontFamily: 'inherit',
                backgroundColor: isActive ? 'var(--acc)' : 'transparent',
                color: isActive ? '#ffffff' : 'var(--ink2)',
                boxShadow: isActive ? '0 2px 10px var(--acc-glow), inset 0 1px 0 rgba(255, 255, 255, 0.2)' : 'none',
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

      {/* Right Controls: Quick Theme Toggle, Live Status & Clock */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          paddingLeft: '6px'
        }}
      >
        {/* Quick Theme Toggle Button */}
        {onToggleQuickTheme && (
          <button
            onClick={onToggleQuickTheme}
            title={isLight ? 'Chuyển sang Giao diện Tối (Dark Mode)' : 'Chuyển sang Giao diện Sáng (Light Mode)'}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '34px',
              height: '34px',
              borderRadius: '9px',
              backgroundColor: 'var(--card)',
              border: '1px solid var(--line2)',
              color: isLight ? '#f59e0b' : '#60a5fa',
              cursor: 'pointer',
              boxShadow: 'var(--shadow-sm)',
              position: 'relative'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--acc)';
              e.currentTarget.style.transform = 'scale(1.05)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--line2)';
              e.currentTarget.style.transform = 'scale(1)';
            }}
          >
            {isLight ? (
              // Sun Icon in Light mode
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
              </svg>
            ) : (
              // Moon Icon in Dark mode
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            )}
          </button>
        )}

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
