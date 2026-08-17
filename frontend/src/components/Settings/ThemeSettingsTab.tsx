import React from 'react';
import type { ThemeMode, AccentColor } from '../../types';

interface ThemeSettingsTabProps {
  themeMode: ThemeMode;
  onSelectThemeMode: (mode: ThemeMode) => void;
  accentColor: AccentColor;
  onSelectAccentColor: (accent: AccentColor) => void;
  glassEffect: boolean;
  onToggleGlassEffect: (val: boolean) => void;
  compactMode: boolean;
  onToggleCompactMode: (val: boolean) => void;
  onResetDefaults: () => void;
}

export const ThemeSettingsTab: React.FC<ThemeSettingsTabProps> = ({
  themeMode,
  onSelectThemeMode,
  accentColor,
  onSelectAccentColor,
  glassEffect,
  onToggleGlassEffect,
  compactMode,
  onToggleCompactMode,
  onResetDefaults
}) => {
  const accents: { id: AccentColor; name: string; hex: string; desc: string }[] = [
    {
      id: 'blue',
      name: 'SentriAI Classic Blue',
      hex: '#3b82f6',
      desc: 'Màu xanh công nghệ mặc định'
    },
    {
      id: 'emerald',
      name: 'Emerald Green',
      hex: '#10b981',
      desc: 'Xanh ngọc lục bảo giám sát an toàn'
    },
    {
      id: 'cyan',
      name: 'Cyan Teal',
      hex: '#06b6d4',
      desc: 'Xanh lơ AI LPR nổi bật'
    },
    {
      id: 'purple',
      name: 'Royal Purple',
      hex: '#a855f7',
      desc: 'Tím thạch anh công nghiệp hiện đại'
    },
    {
      id: 'amber',
      name: 'Amber Orange',
      hex: '#f59e0b',
      desc: 'Cam hổ phách cảnh báo ấm áp'
    }
  ];

  return (
    <div
      className="glass-panel"
      style={{
        borderRadius: '16px',
        overflow: 'hidden',
        boxShadow: 'var(--shadow-lg)'
      }}
    >
      {/* Header with Title & Description */}
      <div
        style={{
          padding: '18px 24px',
          borderBottom: '1px solid var(--line)',
          backgroundColor: 'var(--panel)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px'
        }}
      >
        <div>
          <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--acc)" strokeWidth="2.2">
              <circle cx="12" cy="12" r="5" />
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
            </svg>
            <span>Tùy biến giao diện & Chế độ sáng tối</span>
          </div>
          <div style={{ fontSize: '12.5px', color: 'var(--ink2)', marginTop: '4px' }}>
            Tùy chỉnh chế độ hiển thị, bảng màu chủ đạo và độ tương phản phù hợp với môi trường phòng điều hành hoặc văn phòng.
          </div>
        </div>

        <button
          onClick={onResetDefaults}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 14px',
            borderRadius: '9px',
            border: '1px solid var(--line2)',
            backgroundColor: 'var(--card)',
            color: 'var(--ink2)',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = 'var(--acc)';
            e.currentTarget.style.color = 'var(--ink)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = 'var(--line2)';
            e.currentTarget.style.color = 'var(--ink2)';
          }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
            <path d="M21 3v5h-5" />
            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
            <path d="M3 21v-5h5" />
          </svg>
          <span>Khôi phục mặc định</span>
        </button>
      </div>

      <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '28px' }}>
        {/* Section 1: Theme Mode Selection Cards */}
        <div>
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>1. Chế độ giao diện (Theme Mode)</span>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--acc)',
                  backgroundColor: 'var(--accq)',
                  padding: '2px 8px',
                  borderRadius: '12px'
                }}
              >
                Đang áp dụng: {themeMode === 'dark' ? 'Tối (Dark)' : themeMode === 'light' ? 'Sáng (Light)' : 'Tự động (System)'}
              </span>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--ink3)', marginTop: '2px' }}>
              Chọn chế độ hiển thị phù hợp với điều kiện ánh sáng xung quanh.
            </div>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
              gap: '16px'
            }}
          >
            {/* Card 1: Dark Mode */}
            <div
              onClick={() => onSelectThemeMode('dark')}
              style={{
                borderRadius: '14px',
                border: themeMode === 'dark' ? '2px solid var(--acc)' : '1px solid var(--line2)',
                backgroundColor: 'var(--card)',
                padding: '16px',
                cursor: 'pointer',
                boxShadow: themeMode === 'dark' ? '0 0 20px -2px var(--acc-glow), var(--shadow-md)' : 'var(--shadow-sm)',
                transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                position: 'relative',
                overflow: 'hidden'
              }}
              onMouseEnter={(e) => {
                if (themeMode !== 'dark') e.currentTarget.style.borderColor = 'var(--line3)';
              }}
              onMouseLeave={(e) => {
                if (themeMode !== 'dark') e.currentTarget.style.borderColor = 'var(--line2)';
              }}
            >
              {themeMode === 'dark' && (
                <div
                  style={{
                    position: 'absolute',
                    top: '12px',
                    right: '12px',
                    width: '20px',
                    height: '20px',
                    borderRadius: '50%',
                    backgroundColor: 'var(--acc)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#ffffff',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.3)'
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </div>
              )}

              {/* Theme Mock Visual Preview */}
              <div
                style={{
                  height: '110px',
                  borderRadius: '9px',
                  backgroundColor: '#0b0d11',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  padding: '8px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  marginBottom: '14px',
                  overflow: 'hidden'
                }}
              >
                {/* Mini Header */}
                <div
                  style={{
                    height: '16px',
                    backgroundColor: '#14171f',
                    borderRadius: '5px',
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 8px',
                    justifyContent: 'space-between'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <div style={{ width: '6px', height: '6px', borderRadius: '2px', backgroundColor: '#3b82f6' }} />
                    <div style={{ width: '30px', height: '4px', borderRadius: '2px', backgroundColor: '#ffffff' }} />
                  </div>
                  <div style={{ display: 'flex', gap: '3px' }}>
                    <div style={{ width: '16px', height: '4px', borderRadius: '2px', backgroundColor: '#3b82f6' }} />
                    <div style={{ width: '16px', height: '4px', borderRadius: '2px', backgroundColor: '#303746' }} />
                  </div>
                </div>

                {/* Mini Content */}
                <div style={{ flex: 1, display: 'flex', gap: '6px' }}>
                  {/* Mini Cam Feed */}
                  <div
                    style={{
                      flex: 1.4,
                      backgroundColor: '#1a1e27',
                      borderRadius: '5px',
                      border: '1px solid rgba(255,255,255,0.08)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      position: 'relative'
                    }}
                  >
                    <div
                      style={{
                        width: '32px',
                        height: '16px',
                        border: '1px solid #06b6d4',
                        borderRadius: '2px',
                        backgroundColor: 'rgba(6, 182, 212, 0.15)'
                      }}
                    />
                    <span
                      style={{
                        position: 'absolute',
                        top: '3px',
                        left: '4px',
                        fontSize: '6px',
                        color: '#10b981',
                        fontWeight: 700
                      }}
                    >
                      ● LIVE
                    </span>
                  </div>

                  {/* Mini Event List */}
                  <div
                    style={{
                      flex: 1,
                      backgroundColor: '#14171f',
                      borderRadius: '5px',
                      padding: '4px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '3px'
                    }}
                  >
                    <div style={{ height: '8px', backgroundColor: '#212632', borderRadius: '3px' }} />
                    <div style={{ height: '8px', backgroundColor: '#212632', borderRadius: '3px' }} />
                    <div style={{ height: '8px', backgroundColor: '#212632', borderRadius: '3px' }} />
                  </div>
                </div>
              </div>

              {/* Title & Description */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                <span style={{ fontSize: '14px' }}>🌙</span>
                <span style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--ink)' }}>
                  Giao diện Tối (Dark Industrial)
                </span>
              </div>
              <div style={{ fontSize: '11.5px', color: 'var(--ink2)', lineHeight: 1.45 }}>
                Tối ưu cho trung tâm SOC, phòng giám sát ban đêm, giảm mỏi mắt và làm nổi bật khung hình camera AI.
              </div>
            </div>

            {/* Card 2: Light Mode */}
            <div
              onClick={() => onSelectThemeMode('light')}
              style={{
                borderRadius: '14px',
                border: themeMode === 'light' ? '2px solid var(--acc)' : '1px solid var(--line2)',
                backgroundColor: 'var(--card)',
                padding: '16px',
                cursor: 'pointer',
                boxShadow: themeMode === 'light' ? '0 0 20px -2px var(--acc-glow), var(--shadow-md)' : 'var(--shadow-sm)',
                transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                position: 'relative',
                overflow: 'hidden'
              }}
              onMouseEnter={(e) => {
                if (themeMode !== 'light') e.currentTarget.style.borderColor = 'var(--line3)';
              }}
              onMouseLeave={(e) => {
                if (themeMode !== 'light') e.currentTarget.style.borderColor = 'var(--line2)';
              }}
            >
              {themeMode === 'light' && (
                <div
                  style={{
                    position: 'absolute',
                    top: '12px',
                    right: '12px',
                    width: '20px',
                    height: '20px',
                    borderRadius: '50%',
                    backgroundColor: 'var(--acc)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#ffffff',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.2)'
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </div>
              )}

              {/* Theme Mock Visual Preview */}
              <div
                style={{
                  height: '110px',
                  borderRadius: '9px',
                  backgroundColor: '#f4f6fa',
                  border: '1px solid rgba(0, 0, 0, 0.1)',
                  padding: '8px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  marginBottom: '14px',
                  overflow: 'hidden'
                }}
              >
                {/* Mini Header */}
                <div
                  style={{
                    height: '16px',
                    backgroundColor: '#ffffff',
                    borderRadius: '5px',
                    border: '1px solid rgba(0,0,0,0.08)',
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 8px',
                    justifyContent: 'space-between'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <div style={{ width: '6px', height: '6px', borderRadius: '2px', backgroundColor: '#2563eb' }} />
                    <div style={{ width: '30px', height: '4px', borderRadius: '2px', backgroundColor: '#0f172a' }} />
                  </div>
                  <div style={{ display: 'flex', gap: '3px' }}>
                    <div style={{ width: '16px', height: '4px', borderRadius: '2px', backgroundColor: '#2563eb' }} />
                    <div style={{ width: '16px', height: '4px', borderRadius: '2px', backgroundColor: '#e2e8f0' }} />
                  </div>
                </div>

                {/* Mini Content */}
                <div style={{ flex: 1, display: 'flex', gap: '6px' }}>
                  {/* Mini Cam Feed */}
                  <div
                    style={{
                      flex: 1.4,
                      backgroundColor: '#1e293b',
                      borderRadius: '5px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      position: 'relative'
                    }}
                  >
                    <div
                      style={{
                        width: '32px',
                        height: '16px',
                        border: '1px solid #06b6d4',
                        borderRadius: '2px',
                        backgroundColor: 'rgba(6, 182, 212, 0.2)'
                      }}
                    />
                    <span
                      style={{
                        position: 'absolute',
                        top: '3px',
                        left: '4px',
                        fontSize: '6px',
                        color: '#10b981',
                        fontWeight: 700
                      }}
                    >
                      ● LIVE
                    </span>
                  </div>

                  {/* Mini Event List */}
                  <div
                    style={{
                      flex: 1,
                      backgroundColor: '#ffffff',
                      borderRadius: '5px',
                      border: '1px solid rgba(0,0,0,0.08)',
                      padding: '4px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '3px'
                    }}
                  >
                    <div style={{ height: '8px', backgroundColor: '#f1f4f9', borderRadius: '3px' }} />
                    <div style={{ height: '8px', backgroundColor: '#f1f4f9', borderRadius: '3px' }} />
                    <div style={{ height: '8px', backgroundColor: '#f1f4f9', borderRadius: '3px' }} />
                  </div>
                </div>
              </div>

              {/* Title & Description */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                <span style={{ fontSize: '14px' }}>☀️</span>
                <span style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--ink)' }}>
                  Giao diện Sáng (Modern Light)
                </span>
              </div>
              <div style={{ fontSize: '11.5px', color: 'var(--ink2)', lineHeight: 1.45 }}>
                Tối ưu cho văn phòng điều hành ban ngày, môi trường nhiều ánh sáng tự nhiên và xuất báo cáo dữ liệu.
              </div>
            </div>

            {/* Card 3: System Auto Mode */}
            <div
              onClick={() => onSelectThemeMode('system')}
              style={{
                borderRadius: '14px',
                border: themeMode === 'system' ? '2px solid var(--acc)' : '1px solid var(--line2)',
                backgroundColor: 'var(--card)',
                padding: '16px',
                cursor: 'pointer',
                boxShadow: themeMode === 'system' ? '0 0 20px -2px var(--acc-glow), var(--shadow-md)' : 'var(--shadow-sm)',
                transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                position: 'relative',
                overflow: 'hidden'
              }}
              onMouseEnter={(e) => {
                if (themeMode !== 'system') e.currentTarget.style.borderColor = 'var(--line3)';
              }}
              onMouseLeave={(e) => {
                if (themeMode !== 'system') e.currentTarget.style.borderColor = 'var(--line2)';
              }}
            >
              {themeMode === 'system' && (
                <div
                  style={{
                    position: 'absolute',
                    top: '12px',
                    right: '12px',
                    width: '20px',
                    height: '20px',
                    borderRadius: '50%',
                    backgroundColor: 'var(--acc)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#ffffff',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.2)'
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </div>
              )}

              {/* Theme Mock Visual Preview (Split Dark & Light) */}
              <div
                style={{
                  height: '110px',
                  borderRadius: '9px',
                  background: 'linear-gradient(135deg, #0b0d11 50%, #f4f6fa 50%)',
                  border: '1px solid var(--line2)',
                  padding: '8px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  marginBottom: '14px',
                  overflow: 'hidden',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
              >
                <div
                  style={{
                    backgroundColor: 'var(--panel)',
                    padding: '8px 14px',
                    borderRadius: '20px',
                    border: '1px solid var(--line2)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '11px',
                    fontWeight: 700,
                    color: 'var(--ink)',
                    boxShadow: 'var(--shadow-md)'
                  }}
                >
                  <span>🌙</span>
                  <span style={{ color: 'var(--ink3)' }}>⇄</span>
                  <span>☀️</span>
                  <span>Auto Sync</span>
                </div>
              </div>

              {/* Title & Description */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                <span style={{ fontSize: '14px' }}>💻</span>
                <span style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--ink)' }}>
                  Tự động theo hệ điều hành (System Sync)
                </span>
              </div>
              <div style={{ fontSize: '11.5px', color: 'var(--ink2)', lineHeight: 1.45 }}>
                Tự động đồng bộ giao diện Sáng / Tối theo thiết lập hệ thống máy tính Windows / macOS / Trình duyệt.
              </div>
            </div>
          </div>
        </div>

        {/* Section 2: Accent Color Palette */}
        <div>
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--ink)' }}>
              2. Tông màu chủ đạo (Accent Color Palette)
            </div>
            <div style={{ fontSize: '12px', color: 'var(--ink3)', marginTop: '2px' }}>
              Màu điểm nhấn cho nút bấm chính, tab đang chọn, đường viền active và huy hiệu nổi bật.
            </div>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
              gap: '12px'
            }}
          >
            {accents.map((acc) => {
              const isSelected = accentColor === acc.id;
              return (
                <div
                  key={acc.id}
                  onClick={() => onSelectAccentColor(acc.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '12px 14px',
                    borderRadius: '12px',
                    border: isSelected ? `2px solid ${acc.hex}` : '1px solid var(--line2)',
                    backgroundColor: isSelected ? 'var(--raise)' : 'var(--card)',
                    cursor: 'pointer',
                    boxShadow: isSelected ? `0 2px 12px -2px ${acc.hex}44` : 'none',
                    transition: 'all 0.18s ease'
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.borderColor = 'var(--line3)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) e.currentTarget.style.borderColor = 'var(--line2)';
                  }}
                >
                  <div
                    style={{
                      width: '26px',
                      height: '26px',
                      borderRadius: '8px',
                      backgroundColor: acc.hex,
                      flex: 'none',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#ffffff',
                      boxShadow: `0 2px 6px ${acc.hex}66`
                    }}
                  >
                    {isSelected && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                  </div>

                  <div>
                    <div style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--ink)' }}>
                      {acc.name}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--ink3)' }}>
                      {acc.desc}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Section 3: Advanced Display & Accessibility Preferences */}
        <div>
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--ink)' }}>
              3. Tùy chọn hiển thị nâng cao
            </div>
            <div style={{ fontSize: '12px', color: 'var(--ink3)', marginTop: '2px' }}>
              Cấu hình tối ưu hóa hiệu năng render đồ họa và trải nghiệm hiển thị bảng dữ liệu.
            </div>
          </div>

          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              backgroundColor: 'var(--card)',
              border: '1px solid var(--line2)',
              borderRadius: '14px',
              padding: '16px 20px'
            }}
          >
            {/* Toggle 1: Glassmorphism */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingBottom: '12px',
                borderBottom: '1px solid var(--line)'
              }}
            >
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }}>
                  Hiệu ứng kính mờ (Glassmorphism & Backdrop Blur)
                </div>
                <div style={{ fontSize: '11.5px', color: 'var(--ink3)' }}>
                  Làm mờ nền đằng sau header và các bảng điều khiển dạng kính cao cấp.
                </div>
              </div>

              <button
                onClick={() => onToggleGlassEffect(!glassEffect)}
                style={{
                  width: '46px',
                  height: '26px',
                  borderRadius: '20px',
                  backgroundColor: glassEffect ? 'var(--acc)' : 'var(--raise)',
                  border: '1px solid var(--line2)',
                  padding: '2px',
                  cursor: 'pointer',
                  position: 'relative',
                  transition: 'background-color 0.2s ease'
                }}
              >
                <div
                  style={{
                    width: '20px',
                    height: '20px',
                    borderRadius: '50%',
                    backgroundColor: '#ffffff',
                    transform: glassEffect ? 'translateX(20px)' : 'translateX(0)',
                    transition: 'transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.3)'
                  }}
                />
              </button>
            </div>

            {/* Toggle 2: Compact Mode */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}
            >
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--ink)' }}>
                  Mật độ hiển thị gọn gàng (Compact Mode)
                </div>
                <div style={{ fontSize: '11.5px', color: 'var(--ink3)' }}>
                  Thu nhỏ khoảng cách dòng trong danh sách sự kiện và bảng xe để hiển thị nhiều dữ liệu hơn trên 1 màn hình.
                </div>
              </div>

              <button
                onClick={() => onToggleCompactMode(!compactMode)}
                style={{
                  width: '46px',
                  height: '26px',
                  borderRadius: '20px',
                  backgroundColor: compactMode ? 'var(--acc)' : 'var(--raise)',
                  border: '1px solid var(--line2)',
                  padding: '2px',
                  cursor: 'pointer',
                  position: 'relative',
                  transition: 'background-color 0.2s ease'
                }}
              >
                <div
                  style={{
                    width: '20px',
                    height: '20px',
                    borderRadius: '50%',
                    backgroundColor: '#ffffff',
                    transform: compactMode ? 'translateX(20px)' : 'translateX(0)',
                    transition: 'transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.3)'
                  }}
                />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
