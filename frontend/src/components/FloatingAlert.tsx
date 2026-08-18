import React from 'react';
import type { FloatingNotification } from '../types';

interface FloatingAlertProps {
  notification: FloatingNotification | null;
  onNavigateToMonitor: (camId: string) => void;
  onDismiss: () => void;
}

export const FloatingAlert: React.FC<FloatingAlertProps> = ({ notification, onNavigateToMonitor, onDismiss }) => {
  if (!notification) return null;

  return (
    <div
      className="animate-alert"
      style={{
        position: 'fixed',
        right: '24px',
        bottom: '24px',
        width: '380px',
        maxWidth: 'calc(100vw - 48px)',
        boxSizing: 'border-box',
        backgroundColor: 'rgba(20, 10, 14, 0.95)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        border: '1.5px solid rgba(244, 63, 94, 0.5)',
        borderRadius: '16px',
        padding: '16px 20px',
        boxShadow: '0 20px 40px -8px rgba(0, 0, 0, 0.8), 0 0 24px -2px rgba(244, 63, 94, 0.3)',
        zIndex: 200,
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}
    >
      {/* Top row: Live dot + Title + Time + Close */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span
          className="animate-live"
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: 'var(--p0)',
            display: 'inline-block',
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: '12px',
            fontWeight: 800,
            color: 'var(--p0)',
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
            flex: 1,
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {notification.title}
        </span>
        <span
          style={{
            fontSize: '11px',
            color: 'var(--ink3)',
            fontFamily: 'var(--font-mono)',
            flexShrink: 0,
            marginRight: '4px',
          }}
        >
          {notification.time}
        </span>
        <button
          onClick={onDismiss}
          title="Đóng thông báo"
          style={{
            border: 'none',
            backgroundColor: 'rgba(255, 255, 255, 0.08)',
            color: 'var(--ink2)',
            cursor: 'pointer',
            padding: '4px',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            transition: 'all 0.15s ease',
          }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Middle row: Alert Message */}
      <div
        style={{
          fontSize: '13.5px',
          fontWeight: 600,
          color: '#ffffff',
          lineHeight: 1.45,
          wordBreak: 'break-word',
        }}
      >
        {notification.message}
      </div>

      {/* Bottom row: Zone name + Action button */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          marginTop: '4px',
        }}
      >
        <span
          style={{
            fontSize: '11.5px',
            color: 'var(--ink3)',
            flex: 1,
            minWidth: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {notification.zone}
        </span>
        <button
          onClick={() => onNavigateToMonitor(notification.camId)}
          style={{
            fontSize: '12px',
            fontWeight: 700,
            padding: '7px 14px',
            borderRadius: '8px',
            border: 'none',
            backgroundColor: 'var(--p0)',
            color: '#ffffff',
            cursor: 'pointer',
            fontFamily: 'inherit',
            flexShrink: 0,
            whiteSpace: 'nowrap',
            boxShadow: '0 4px 14px rgba(244, 63, 94, 0.45)',
            transition: 'all 0.15s ease',
          }}
        >
          Xem camera ngay →
        </button>
      </div>
    </div>
  );
};
