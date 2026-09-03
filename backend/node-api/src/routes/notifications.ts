/**
 * routes/notifications.ts — Notification Settings & Test REST Router
 *
 * GET  /api/v1/notifications/settings
 * PUT  /api/v1/notifications/settings
 * POST /api/v1/notifications/test
 */
import { Router, Request, Response, NextFunction } from 'express';
import {
  getNotificationSettings,
  updateNotificationSettings,
  type NotificationSettings,
} from '../services/notificationConfigService';
import { testTelegramConnection } from '../services/telegramService';
import { testEmailConnection } from '../services/emailService';
import { sendSuccess, sendError } from '../utils/response';

export const notificationsRouter = Router();

/**
 * GET /api/v1/notifications/settings
 */
notificationsRouter.get('/settings', (req: Request, res: Response) => {
  const settings = getNotificationSettings();
  return sendSuccess(res, settings);
});

/**
 * PUT /api/v1/notifications/settings
 */
notificationsRouter.put('/settings', (req: Request, res: Response, next: NextFunction) => {
  try {
    const updates = req.body as Partial<NotificationSettings>;
    const updated = updateNotificationSettings(updates);
    return sendSuccess(res, updated);
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /api/v1/notifications/test
 * Body: { channel: 'telegram' | 'email', telegramConfig?, emailConfig? }
 */
notificationsRouter.post('/test', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { channel, telegramConfig, emailConfig } = req.body;
    const current = getNotificationSettings();

    if (channel === 'telegram') {
      const token = telegramConfig?.botToken || current.telegram.botToken;
      const chatId = telegramConfig?.chatId || current.telegram.chatId;

      if (!token || !chatId) {
        return sendError(res, 400, 'VALIDATION_ERROR', 'Vui lòng cung cấp Bot Token và Chat ID để kiểm tra kết nối Telegram.');
      }

      const result = await testTelegramConnection(token, chatId);
      if (result.success) {
        return sendSuccess(res, { success: true, message: 'Đã gửi tin nhắn kiểm tra thành công tới Telegram!' });
      }
      return sendError(res, 400, 'TELEGRAM_ERROR', `Gửi tin nhắn Telegram thất bại: ${result.error}`);
    }

    if (channel === 'email') {
      const config = {
        ...current.email,
        ...(emailConfig || {}),
      };

      if (!config.smtpUser || !config.smtpPass || !config.toEmails || config.toEmails.length === 0) {
        return sendError(res, 400, 'VALIDATION_ERROR', 'Vui lòng điền đủ Tài khoản SMTP, Mật khẩu và Email người nhận.');
      }

      const result = await testEmailConnection(config);
      if (result.success) {
        return sendSuccess(res, { success: true, message: 'Đã gửi email kiểm tra thành công!' });
      }
      return sendError(res, 400, 'EMAIL_ERROR', `Gửi email kiểm tra thất bại: ${result.error}`);
    }

    return sendError(res, 400, 'VALIDATION_ERROR', 'Vui lòng chỉ định kênh kiểm tra: telegram hoặc email.');
  } catch (err) {
    return next(err);
  }
});
