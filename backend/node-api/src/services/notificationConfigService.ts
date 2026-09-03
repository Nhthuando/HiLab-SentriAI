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

function findEnvFilePath(): string | null {
  const candidates = [
    path.resolve(__dirname, '../../../.env'),
    path.resolve(__dirname, '../../.env'),
    path.resolve(process.cwd(), '../.env'),
    path.resolve(process.cwd(), '.env'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      return c;
    }
  }
  return candidates[0];
}

function updateEnvFile(updates: Record<string, string | number | boolean>): void {
  const envPath = findEnvFilePath();
  if (!envPath) return;

  try {
    let content = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf8') : '';
    for (const [key, val] of Object.entries(updates)) {
      const stringVal = String(val);
      const regex = new RegExp(`^${key}=.*$`, 'm');
      const formattedVal =
        stringVal.includes(' ') || stringVal.includes('@') || stringVal.includes(':')
          ? `"${stringVal}"`
          : stringVal;
      if (regex.test(content)) {
        content = content.replace(regex, `${key}=${formattedVal}`);
      } else {
        content = content.trimEnd() + `\n${key}=${formattedVal}\n`;
      }
      process.env[key] = stringVal;
    }
    fs.writeFileSync(envPath, content, 'utf8');
  } catch (err) {
    console.warn('[NotificationConfig] Could not write to .env file:', err);
  }
}

function getDefaultConfig(): NotificationSettings {
  const telegramToken = process.env.TELEGRAM_BOT_TOKEN || '';
  const telegramChatId = process.env.TELEGRAM_CHAT_ID || '';
  const telegramEnabled =
    process.env.TELEGRAM_NOTIFICATIONS_ENABLED !== undefined
      ? process.env.TELEGRAM_NOTIFICATIONS_ENABLED === 'true'
      : Boolean(telegramToken && telegramChatId);

  const smtpHost = process.env.SMTP_HOST || 'smtp.gmail.com';
  const smtpPort = Number(process.env.SMTP_PORT || 587);
  const smtpUser = process.env.SMTP_USER || '';
  const smtpPass = process.env.SMTP_PASS || '';
  const fromEmail = process.env.ALERT_FROM_EMAIL || smtpUser || 'no-reply@sentriai.local';
  const toEmailsRaw = process.env.ALERT_TO_EMAILS || '';
  const toEmails = toEmailsRaw
    ? toEmailsRaw.split(',').map((s) => s.trim()).filter(Boolean)
    : [];
  const emailEnabled =
    process.env.EMAIL_NOTIFICATIONS_ENABLED !== undefined
      ? process.env.EMAIL_NOTIFICATIONS_ENABLED === 'true'
      : Boolean(smtpUser && smtpPass && toEmails.length > 0);

  return {
    telegram: {
      enabled: telegramEnabled,
      botToken: telegramToken,
      chatId: telegramChatId,
    },
    email: {
      enabled: emailEnabled,
      smtpHost,
      smtpPort,
      smtpSecure: smtpPort === 465,
      smtpUser,
      smtpPass,
      fromEmail,
      toEmails,
    },
    cooldownSeconds: Number(process.env.NOTIFICATION_COOLDOWN_SECONDS || 180),
  };
}

let cachedSettings: NotificationSettings | null = null;

export function getNotificationSettings(): NotificationSettings {
  if (cachedSettings) {
    return cachedSettings;
  }

  const envConfig = getDefaultConfig();
  const filePath = getConfigFilePath();

  if (fs.existsSync(filePath)) {
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      const parsed = JSON.parse(content);
      cachedSettings = {
        ...envConfig,
        ...parsed,
        telegram: {
          enabled: parsed.telegram?.enabled ?? envConfig.telegram.enabled,
          botToken: parsed.telegram?.botToken || envConfig.telegram.botToken,
          chatId: parsed.telegram?.chatId || envConfig.telegram.chatId,
        },
        email: {
          ...envConfig.email,
          ...(parsed.email || {}),
          smtpUser: parsed.email?.smtpUser || envConfig.email.smtpUser,
          smtpPass: parsed.email?.smtpPass || envConfig.email.smtpPass,
        },
        cooldownSeconds: parsed.cooldownSeconds ?? envConfig.cooldownSeconds,
      };
      return cachedSettings!;
    } catch (err) {
      console.warn('[NotificationConfig] Failed to parse config file, using defaults:', err);
    }
  }

  cachedSettings = envConfig;
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

  // 1. Sync to backend/.env so secrets are stored exclusively in env
  updateEnvFile({
    TELEGRAM_BOT_TOKEN: next.telegram.botToken,
    TELEGRAM_CHAT_ID: next.telegram.chatId,
    TELEGRAM_NOTIFICATIONS_ENABLED: String(next.telegram.enabled),
    SMTP_HOST: next.email.smtpHost,
    SMTP_PORT: String(next.email.smtpPort),
    SMTP_USER: next.email.smtpUser,
    SMTP_PASS: next.email.smtpPass,
    ALERT_FROM_EMAIL: next.email.fromEmail,
    ALERT_TO_EMAILS: next.email.toEmails.join(','),
    NOTIFICATION_COOLDOWN_SECONDS: String(next.cooldownSeconds),
  });

  // 2. Persist to data directory (which is in .gitignore)
  const filePath = getConfigFilePath();
  try {
    fs.writeFileSync(filePath, JSON.stringify(next, null, 2), 'utf8');
  } catch (err) {
    console.error('[NotificationConfig] Failed to save config to disk:', err);
  }

  cachedSettings = next;
  return next;
}
