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
        maxWidth: '400px',
        backgroundColor: 'rgba(28, 12, 16, 0.88)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        border: '1.5px solid rgba(244, 63, 94, 0.45)',
        borderRadius: '16px',
        padding: '16px 18px',
        boxShadow: '0 16px 40px -4px rgba(244, 63, 94, 0.35), 0 0 0 1px rgba(244, 63, 94, 0.2)',
        zIndex: 100,
        display: 'flex',
        flexDirection: 'column',
        gap: '10px'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '9px' }}>
        <span
          className="animate-live"
          style={{
            width: '9px',
            height: '9px',
            borderRadius: '50%',
            backgroundColor: 'var(--p0)',
            display: 'inline-block'
          }}
        />
        <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--p0)', flex: 1, letterSpacing: '0.02em' }}>
          {notification.title}
        </span>
        <span style={{ fontSize: '11px', color: 'var(--ink3)', fontFamily: 'var(--font-mono)' }}>
          {notification.time}
        </span>
        <button
          onClick={onDismiss}
          title="Đóng thông báo"
          style={{
            border: 'none',
            backgroundColor: 'transparent',
            color: 'var(--ink3)',
            cursor: 'pointer',
            padding: '2px',
            display: 'flex',
            alignItems: 'center'
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div style={{ fontSize: '13px', color: 'var(--ink)', lineHeight: 1.5 }}>
        {notification.message}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '4px' }}>
        <span style={{ fontSize: '11.5px', color: 'var(--ink3)' }}>{notification.zone}</span>
        <button
          onClick={() => onNavigateToMonitor(notification.camId)}
          style={{
            fontSize: '12px',
            fontWeight: 700,
            padding: '6px 14px',
            borderRadius: '8px',
            border: 'none',
            backgroundColor: 'var(--p0)',
            color: '#ffffff',
            cursor: 'pointer',
            fontFamily: 'inherit',
            boxShadow: '0 2px 8px rgba(244, 63, 94, 0.4)'
          }}
        >
          Xem camera ngay →
        </button>
      </div>
    </div>
  );
};
