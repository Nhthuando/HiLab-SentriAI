import React, { useState, useEffect } from 'react';
import { API_BASE_URL } from '../../api/client';

interface TelegramConfig {
  enabled: boolean;
  botToken: string;
  chatId: string;
}

interface EmailConfig {
  enabled: boolean;
  smtpHost: string;
  smtpPort: number;
  smtpSecure: boolean;
  smtpUser: string;
  smtpPass: string;
  fromEmail: string;
  toEmails: string[];
}

interface NotificationSettings {
  telegram: TelegramConfig;
  email: EmailConfig;
  cooldownSeconds: number;
}

export const NotificationTab: React.FC = () => {
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [toEmailsInput, setToEmailsInput] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [testTelegramStatus, setTestTelegramStatus] = useState<{ loading: boolean; message?: string; error?: string } | null>(null);
  const [testEmailStatus, setTestEmailStatus] = useState<{ loading: boolean; message?: string; error?: string } | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/notifications/settings`);
      const json = await res.json();
      if (json.success && json.data) {
        setSettings(json.data);
        setToEmailsInput((json.data.email?.toEmails || []).join(', '));
      }
    } catch (err: any) {
      console.error('Error fetching notification settings:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!settings) return;

    setIsSaving(true);
    setSaveMessage(null);
    setSaveError(null);

    const emailList = toEmailsInput
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const payload: NotificationSettings = {
      ...settings,
      email: {
        ...settings.email,
        toEmails: emailList,
      },
    };

    try {
      const res = await fetch(`${API_BASE_URL}/notifications/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const json = await res.json();
      if (json.success) {
        setSettings(json.data);
        setSaveMessage('Đã lưu cấu hình thông báo thành công!');
        setTimeout(() => setSaveMessage(null), 4000);
      } else {
        setSaveError(json.error?.message || 'Không thể lưu cấu hình.');
      }
    } catch (err: any) {
      setSaveError(err.message || 'Lỗi mạng khi lưu cấu hình.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleTestTelegram = async () => {
    if (!settings) return;
    setTestTelegramStatus({ loading: true });
    try {
      const res = await fetch(`${API_BASE_URL}/notifications/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel: 'telegram',
          telegramConfig: settings.telegram,
        }),
      });
      const json = await res.json();
      if (json.success) {
        setTestTelegramStatus({ loading: false, message: 'Gửi tin nhắn Telegram thành công! Hãy kiểm tra nhóm chat.' });
      } else {
        setTestTelegramStatus({ loading: false, error: json.error?.message || 'Gửi thất bại.' });
      }
    } catch (err: any) {
      setTestTelegramStatus({ loading: false, error: err.message || 'Lỗi kết nối test.' });
    }
  };

  const handleTestEmail = async () => {
    if (!settings) return;
    setTestEmailStatus({ loading: true });
    const emailList = toEmailsInput
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    try {
      const res = await fetch(`${API_BASE_URL}/notifications/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel: 'email',
          emailConfig: {
            ...settings.email,
            toEmails: emailList,
          },
        }),
      });
      const json = await res.json();
      if (json.success) {
        setTestEmailStatus({ loading: false, message: 'Đã gửi email kiểm tra thành công! Hãy kiểm tra hòm thư.' });
      } else {
        setTestEmailStatus({ loading: false, error: json.error?.message || 'Gửi email thất bại.' });
      }
    } catch (err: any) {
      setTestEmailStatus({ loading: false, error: err.message || 'Lỗi kết nối test.' });
    }
  };

  if (isLoading || !settings) {
    return (
      <div style={{ padding: '32px', textAlign: 'center', color: 'var(--ink2)' }}>
        Đang tải cấu hình thông báo...
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '16px', maxWidth: '840px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--line)', paddingBottom: '12px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '18px', color: 'var(--ink)' }}>Cấu hình Cảnh báo & Thông báo Đa kênh</h2>
          <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--ink2)' }}>
            Tự động gửi cảnh báo vi phạm khu vực (Bãi kiểm) và xe lạ qua cổng tới Telegram và Email
          </p>
        </div>
      </div>

      {saveMessage && (
        <div style={{ padding: '10px 14px', borderRadius: '8px', background: 'rgba(34, 197, 94, 0.15)', color: '#22c55e', fontSize: '13px', border: '1px solid #22c55e' }}>
          ✓ {saveMessage}
        </div>
      )}
      {saveError && (
        <div style={{ padding: '10px 14px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', fontSize: '13px', border: '1px solid #ef4444' }}>
          ✕ {saveError}
        </div>
      )}

      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        {/* SECTION 1: TELEGRAM BOT */}
        <div className="glass-panel" style={{ padding: '20px', borderRadius: '12px', background: 'var(--card)', border: '1px solid var(--line)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '20px' }}>📱</span>
              <div>
                <h3 style={{ margin: 0, fontSize: '15px', color: 'var(--ink)' }}>Kênh Telegram Bot (Khuyên dùng cho Bảo vệ)</h3>
                <span style={{ fontSize: '11.5px', color: 'var(--ink2)' }}>Gửi tin nhắn tức thì kèm ảnh chụp vi phạm cho điện thoại tuần tra</span>
              </div>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: 'var(--ink)' }}>
              <input
                type="checkbox"
                checked={settings.telegram.enabled}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    telegram: { ...settings.telegram, enabled: e.target.checked },
                  })
                }
                style={{ width: '16px', height: '16px', accentColor: 'var(--acc)' }}
              />
              Bật thông báo Telegram
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--ink2)', marginBottom: '6px' }}>
                Telegram Bot Token:
              </label>
              <input
                type="text"
                placeholder="VD: 123456789:ABCdefGhIJKlmNoPQRstuVWxYz"
                value={settings.telegram.botToken}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    telegram: { ...settings.telegram, botToken: e.target.value },
                  })
                }
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  background: 'var(--bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--ink)',
                  fontSize: '12.5px',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--ink2)', marginBottom: '6px' }}>
                Chat ID / Group ID:
              </label>
              <input
                type="text"
                placeholder="VD: -1001234567890 hoặc 987654321"
                value={settings.telegram.chatId}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    telegram: { ...settings.telegram, chatId: e.target.value },
                  })
                }
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  background: 'var(--bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--ink)',
                  fontSize: '12.5px',
                }}
              />
            </div>
          </div>

          <div style={{ marginTop: '14px', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button
              type="button"
              onClick={handleTestTelegram}
              disabled={testTelegramStatus?.loading || !settings.telegram.botToken || !settings.telegram.chatId}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                background: 'color-mix(in srgb, var(--acc) 20%, var(--card))',
                border: '1px solid var(--acc)',
                color: 'var(--ink)',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {testTelegramStatus?.loading ? 'Đang gửi test...' : '🔔 Gửi thử tin nhắn Telegram'}
            </button>
            {testTelegramStatus?.message && (
              <span style={{ fontSize: '12px', color: '#22c55e' }}>✓ {testTelegramStatus.message}</span>
            )}
            {testTelegramStatus?.error && (
              <span style={{ fontSize: '12px', color: '#ef4444' }}>✕ {testTelegramStatus.error}</span>
            )}
          </div>

          {/* Quick Guide */}
          <div style={{ marginTop: '14px', padding: '12px 14px', borderRadius: '8px', background: 'rgba(59, 130, 246, 0.08)', border: '1px dashed rgba(59, 130, 246, 0.3)', fontSize: '12px', lineHeight: '1.6', color: 'var(--ink2)' }}>
            <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>💡</span> Hướng dẫn nhanh lấy Bot Token & Chat ID Telegram (2 phút):
            </div>
            <ol style={{ margin: '4px 0 0', paddingLeft: '18px' }}>
              <li>Mở Telegram tìm <b>@BotFather</b> ➔ Gõ <code>/newbot</code>, nhập tên bot và username (kết thúc bằng <i>_bot</i>). BotFather sẽ trả về chuỗi <b>HTTP API Token</b> ➔ Copy dán vào ô <i>Telegram Bot Token</i>.</li>
              <li>Nhấn vào link con bot bạn vừa tạo và bấm <b>START</b> (hoặc thêm bot vào Group của bạn nếu muốn gửi theo nhóm).</li>
              <li>Tìm bot <b>@userinfobot</b> trên Telegram và gửi tin bất kỳ ➔ Copy số <b>Id</b> ➔ Dán vào ô <i>Chat ID / Group ID</i>.</li>
              <li>Bật checkbox <b>Bật thông báo Telegram</b>, nhấn nút <b>🔔 Gửi thử tin nhắn Telegram</b> để nhận tin nhắn mẫu, rồi bấm <b>Lưu cấu hình</b> ở góc dưới.</li>
            </ol>
          </div>
        </div>

        {/* SECTION 2: EMAIL SMTP */}
        <div className="glass-panel" style={{ padding: '20px', borderRadius: '12px', background: 'var(--card)', border: '1px solid var(--line)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '20px' }}>✉️</span>
              <div>
                <h3 style={{ margin: 0, fontSize: '15px', color: 'var(--ink)' }}>Kênh Email (Báo cáo & Lưu vết Ban quản lý)</h3>
                <span style={{ fontSize: '11.5px', color: 'var(--ink2)' }}>Gửi email HTML chi tiết khi phát hiện sự cố an ninh nghiêm trọng</span>
              </div>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', color: 'var(--ink)' }}>
              <input
                type="checkbox"
                checked={settings.email.enabled}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    email: { ...settings.email, enabled: e.target.checked },
                  })
                }
                style={{ width: '16px', height: '16px', accentColor: 'var(--acc)' }}
              />
              Bật thông báo Email
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '14px', marginBottom: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--ink2)', marginBottom: '6px' }}>
                Máy chủ SMTP Host:
              </label>
              <input
                type="text"
                placeholder="VD: smtp.gmail.com"
                value={settings.email.smtpHost}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    email: { ...settings.email, smtpHost: e.target.value },
                  })
                }
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  background: 'var(--bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--ink)',
                  fontSize: '12px',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--ink2)', marginBottom: '6px' }}>
                Cổng SMTP:
              </label>
              <input
                type="number"
                placeholder="587 hoặc 465"
                value={settings.email.smtpPort}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    email: {
                      ...settings.email,
                      smtpPort: Number(e.target.value),
                      smtpSecure: Number(e.target.value) === 465,
                    },
                  })
                }
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  background: 'var(--bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--ink)',
                  fontSize: '12px',
                }}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--ink2)', marginBottom: '6px' }}>
                Tài khoản gửi (SMTP User):
              </label>
              <input
                type="text"
                placeholder="VD: sentriai.alerts@gmail.com"
                value={settings.email.smtpUser}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    email: { ...settings.email, smtpUser: e.target.value },
                  })
                }
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  background: 'var(--bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--ink)',
                  fontSize: '12px',
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--ink2)', marginBottom: '6px' }}>
                Mật khẩu ứng dụng (SMTP Pass):
              </label>
              <input
                type="password"
                placeholder="Mật khẩu App Gmail"
                value={settings.email.smtpPass}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    email: { ...settings.email, smtpPass: e.target.value },
                  })
                }
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  background: 'var(--bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--ink)',
                  fontSize: '12px',
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--ink2)', marginBottom: '6px' }}>
              Danh sách Email nhận cảnh báo (phân cách bằng dấu phẩy):
            </label>
            <input
              type="text"
              placeholder="VD: truongphong@company.com, baove@company.com"
              value={toEmailsInput}
              onChange={(e) => setToEmailsInput(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '8px',
                background: 'var(--bg)',
                border: '1px solid var(--line)',
                color: 'var(--ink)',
                fontSize: '12px',
              }}
            />
          </div>

          <div style={{ marginTop: '14px', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button
              type="button"
              onClick={handleTestEmail}
              disabled={testEmailStatus?.loading || !settings.email.smtpUser || !settings.email.smtpPass}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                background: 'color-mix(in srgb, var(--acc) 20%, var(--card))',
                border: '1px solid var(--acc)',
                color: 'var(--ink)',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {testEmailStatus?.loading ? 'Đang gửi test...' : '✉️ Gửi thử email kiểm tra'}
            </button>
            {testEmailStatus?.message && (
              <span style={{ fontSize: '12px', color: '#22c55e' }}>✓ {testEmailStatus.message}</span>
            )}
            {testEmailStatus?.error && (
              <span style={{ fontSize: '12px', color: '#ef4444' }}>✕ {testEmailStatus.error}</span>
            )}
          </div>
        </div>

        {/* SECTION 3: ANTI-SPAM DEBOUNCE */}
        <div className="glass-panel" style={{ padding: '16px 20px', borderRadius: '12px', background: 'var(--card)', border: '1px solid var(--line)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h4 style={{ margin: 0, fontSize: '13.5px', color: 'var(--ink)' }}>Thời gian Cooldown chống Spam thông báo</h4>
            <span style={{ fontSize: '11.5px', color: 'var(--ink2)' }}>Cùng một đối tượng vi phạm hoặc biển số sẽ không gửi cảnh báo lặp lại trong khoảng này</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="number"
              min="10"
              max="3600"
              value={settings.cooldownSeconds}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  cooldownSeconds: Math.max(10, Number(e.target.value) || 180),
                })
              }
              style={{
                width: '80px',
                padding: '6px 10px',
                borderRadius: '6px',
                background: 'var(--bg)',
                border: '1px solid var(--line)',
                color: 'var(--ink)',
                fontSize: '13px',
                textAlign: 'center',
              }}
            />
            <span style={{ fontSize: '12.5px', color: 'var(--ink2)' }}>giây</span>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '8px' }}>
          <button
            type="submit"
            disabled={isSaving}
            style={{
              padding: '10px 24px',
              borderRadius: '9px',
              background: 'var(--acc)',
              color: '#ffffff',
              border: 'none',
              fontSize: '13.5px',
              fontWeight: 650,
              cursor: 'pointer',
              boxShadow: '0 2px 8px var(--acc-glow)',
            }}
          >
            {isSaving ? 'Đang lưu...' : '💾 Lưu Cấu hình Thông Báo'}
          </button>
        </div>
      </form>
    </div>
  );
};
