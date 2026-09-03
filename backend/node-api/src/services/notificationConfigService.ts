/**
 * notificationConfigService.ts — Manages notification configuration for Telegram and Email
 *
 * Reads/writes config persisted in data/notifications_config.json with fallback to .env
 */
import fs from 'fs';
import path from 'path';

export interface TelegramConfig {
  enabled: boolean;
  botToken: string;
  chatId: string;
}

export interface EmailConfig {
  enabled: boolean;
  smtpHost: string;
  smtpPort: number;
  smtpSecure: boolean;
  smtpUser: string;
  smtpPass: string;
  fromEmail: string;
  toEmails: string[];
}

export interface NotificationSettings {
  telegram: TelegramConfig;
  email: EmailConfig;
  cooldownSeconds: number;
}

function getConfigFilePath(): string {
  const backendDir = path.resolve(__dirname, '../..');
  const dataDir = path.resolve(backendDir, 'data');
  if (!fs.existsSync(dataDir)) {
    try {
      fs.mkdirSync(dataDir, { recursive: true });
    } catch {
      // ignore
    }
  }
  return path.resolve(dataDir, 'notifications_config.json');
}

function getDefaultConfig(): NotificationSettings {
  const telegramToken = process.env.TELEGRAM_BOT_TOKEN || '';
  const telegramChatId = process.env.TELEGRAM_CHAT_ID || '';
  const smtpHost = process.env.SMTP_HOST || 'smtp.gmail.com';
  const smtpPort = Number(process.env.SMTP_PORT || 587);
  const smtpUser = process.env.SMTP_USER || '';
  const smtpPass = process.env.SMTP_PASS || '';
  const fromEmail = process.env.ALERT_FROM_EMAIL || smtpUser || 'no-reply@sentriai.local';
  const toEmailsRaw = process.env.ALERT_TO_EMAILS || '';
  const toEmails = toEmailsRaw
    ? toEmailsRaw.split(',').map((s) => s.trim()).filter(Boolean)
    : [];

  return {
    telegram: {
      enabled: Boolean(telegramToken && telegramChatId),
      botToken: telegramToken,
      chatId: telegramChatId,
    },
    email: {
      enabled: Boolean(smtpUser && smtpPass && toEmails.length > 0),
      smtpHost,
      smtpPort,
      smtpSecure: smtpPort === 465,
      smtpUser,
      smtpPass,
      fromEmail,
      toEmails,
    },
    cooldownSeconds: 180, // 3 minutes debounce per object/zone
  };
}

let cachedSettings: NotificationSettings | null = null;

export function getNotificationSettings(): NotificationSettings {
  if (cachedSettings) {
    return cachedSettings;
  }

  const filePath = getConfigFilePath();
  if (fs.existsSync(filePath)) {
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      const parsed = JSON.parse(content);
      cachedSettings = {
        ...getDefaultConfig(),
        ...parsed,
        telegram: { ...getDefaultConfig().telegram, ...(parsed.telegram || {}) },
        email: { ...getDefaultConfig().email, ...(parsed.email || {}) },
      };
      return cachedSettings!;
    } catch (err) {
      console.warn('[NotificationConfig] Failed to parse config file, using defaults:', err);
    }
  }

  cachedSettings = getDefaultConfig();
  return cachedSettings;
}

export function updateNotificationSettings(updates: Partial<NotificationSettings>): NotificationSettings {
  const current = getNotificationSettings();
  const next: NotificationSettings = {
    ...current,
    ...updates,
    telegram: {
      ...current.telegram,
      ...(updates.telegram || {}),
    },
    email: {
      ...current.email,
      ...(updates.email || {}),
    },
    cooldownSeconds: updates.cooldownSeconds ?? current.cooldownSeconds,
  };

  const filePath = getConfigFilePath();
  try {
    fs.writeFileSync(filePath, JSON.stringify(next, null, 2), 'utf8');
    cachedSettings = next;
  } catch (err) {
    console.error('[NotificationConfig] Failed to save config to disk:', err);
  }

  return next;
}
