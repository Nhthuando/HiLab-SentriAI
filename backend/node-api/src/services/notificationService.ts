/**
 * notificationService.ts — Central coordinator for incident notifications with anti-spam cooldown
 */
import path from 'path';
import fs from 'fs';
import { getNotificationSettings } from './notificationConfigService';
import { sendTelegramMessage } from './telegramService';
import { sendEmailAlert, renderAlertEmailHtml } from './emailService';

// In-memory debounce cache: key -> timestamp (epoch ms)
const cooldownMap = new Map<string, number>();

function resolveLocalMediaFile(relPath?: string | null): string | null {
  if (!relPath) return null;
  if (path.isAbsolute(relPath) && fs.existsSync(relPath)) {
    return relPath;
  }
  const backendDir = path.resolve(__dirname, '../..');
  const candidates = [
    path.resolve(backendDir, relPath),
    path.resolve(backendDir, 'data', relPath),
    path.resolve(backendDir, 'data/crops', path.basename(relPath)),
    path.resolve(backendDir, 'data/clips', path.basename(relPath)),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      return c;
    }
  }
  return null;
}

export class NotificationService {
  /**
   * Check whether an event key is in cooldown
   */
  private isCoolingDown(key: string, cooldownSec: number): boolean {
    const now = Date.now();
    const last = cooldownMap.get(key);
    if (last && now - last < cooldownSec * 1000) {
      return true;
    }
    cooldownMap.set(key, now);
    return false;
  }

  /**
   * Dispatch notification for Area Zone Violation
   */
  public async notifyAreaViolation(violation: {
    id: string;
    cameraId: string;
    zoneName: string;
    objectLabel: string;
    enteredAt: Date | string;
    cropPath?: string | null;
  }): Promise<void> {
    try {
      const settings = getNotificationSettings();
      if (!settings.telegram.enabled && !settings.email.enabled) {
        return;
      }

      const debounceKey = `area:${violation.cameraId}:${violation.zoneName}:${violation.objectLabel}`;
      if (this.isCoolingDown(debounceKey, settings.cooldownSeconds)) {
        console.log(`[NotificationService] Cooldown active for ${debounceKey}, skipping alert.`);
        return;
      }

      const enteredStr =
        violation.enteredAt instanceof Date
          ? violation.enteredAt.toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' })
          : new Date(violation.enteredAt).toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' });

      const photoPath = resolveLocalMediaFile(violation.cropPath);

      // 1. Dispatch Telegram
      if (settings.telegram.enabled && settings.telegram.botToken && settings.telegram.chatId) {
        const tgMsg =
          `🚨 <b>[CẢNH BÁO VI PHẠM KHU VỰC]</b>\n\n` +
          `📍 <b>Vị trí:</b> ${violation.cameraId} · <b>Zone:</b> ${violation.zoneName}\n` +
          `⚠️ <b>Đối tượng vi phạm:</b> <code>${violation.objectLabel}</code>\n` +
          `⏰ <b>Thời điểm vào:</b> ${enteredStr}\n` +
          `🆔 <b>Mã sự cố:</b> <code>${violation.id.slice(0, 8)}</code>\n\n` +
          `<i>Hệ thống SentriAI đang giám sát thời gian lưu trú trong zone.</i>`;

        sendTelegramMessage(
          settings.telegram.botToken,
          settings.telegram.chatId,
          tgMsg,
          photoPath,
        ).catch((err) => console.warn('[NotificationService] Telegram dispatch failed:', err));
      }

      // 2. Dispatch Email
      if (settings.email.enabled && settings.email.toEmails.length > 0) {
        const emailHtml = renderAlertEmailHtml({
          title: `Cảnh báo vi phạm khu vực: ${violation.objectLabel} tại ${violation.zoneName}`,
          badgeText: 'VI PHẠM ZONE',
          badgeColor: '#e63946',
          details: [
            { label: 'Camera / Vị trí', value: violation.cameraId },
            { label: 'Khu vực / Zone', value: violation.zoneName },
            { label: 'Đối tượng phát hiện', value: violation.objectLabel },
            { label: 'Thời điểm bắt đầu', value: enteredStr },
            { label: 'Mã sự cố (UUID)', value: violation.id },
          ],
          note: 'Đối tượng đã đi vào khu vực cấm hoặc hoạt động ngoài khung giờ cho phép.',
        });

        sendEmailAlert(
          settings.email,
          `[SentriAI Alert] Vi phạm khu vực: ${violation.objectLabel} - ${violation.zoneName}`,
          emailHtml,
          photoPath,
        ).catch((err) => console.warn('[NotificationService] Email dispatch failed:', err));
      }
    } catch (err) {
      console.error('[NotificationService] Unexpected error in notifyAreaViolation:', err);
    }
  }

  /**
   * Dispatch notification for Stranger Vehicle at Gate
   */
  public async notifyGateStranger(event: {
    id: string;
    cameraId: string;
    lane: string;
    licensePlate: string;
    confidence: number;
    cropPath?: string | null;
    eventTimestamp: Date | string;
  }): Promise<void> {
    try {
      const settings = getNotificationSettings();
      if (!settings.telegram.enabled && !settings.email.enabled) {
        return;
      }

      const debounceKey = `gate:${event.licensePlate}`;
      if (this.isCoolingDown(debounceKey, settings.cooldownSeconds)) {
        return;
      }

      const timeStr =
        event.eventTimestamp instanceof Date
          ? event.eventTimestamp.toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' })
          : new Date(event.eventTimestamp).toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' });

      const photoPath = resolveLocalMediaFile(event.cropPath);
      const laneName = event.lane === 'IN_2' ? 'Làn IN 2 (Làn phụ)' : 'Làn IN 1 (Cổng chính)';
      const confPercent = Math.round(event.confidence * 100);

      // 1. Dispatch Telegram
      if (settings.telegram.enabled && settings.telegram.botToken && settings.telegram.chatId) {
        const tgMsg =
          `⚠️ <b>[PHÁT HIỆN PHƯƠNG TIỆN LẠ QUA CỔNG]</b>\n\n` +
          `🚗 <b>Biển số:</b> <code>${event.licensePlate}</code> (Độ tin cậy: ${confPercent}%)\n` +
          `📍 <b>Làn kiểm soát:</b> ${laneName}\n` +
          `⏰ <b>Thời điểm vào:</b> ${timeStr}\n\n` +
          `<i>Phương tiện chưa được đăng ký trong danh mục XE QUEN. Vui lòng kiểm tra giấy tờ nếu cần.</i>`;

        sendTelegramMessage(
          settings.telegram.botToken,
          settings.telegram.chatId,
          tgMsg,
          photoPath,
        ).catch((err) => console.warn('[NotificationService] Gate Telegram dispatch failed:', err));
      }

      // 2. Dispatch Email
      if (settings.email.enabled && settings.email.toEmails.length > 0) {
        const emailHtml = renderAlertEmailHtml({
          title: `Phát hiện xe lạ vào cổng: ${event.licensePlate}`,
          badgeText: 'XE LẠ QUA CỔNG',
          badgeColor: '#f59e0b',
          details: [
            { label: 'Biển số nhận diện', value: event.licensePlate },
            { label: 'Độ tin cậy nhận diện', value: `${confPercent}%` },
            { label: 'Làn vào', value: laneName },
            { label: 'Thời gian', value: timeStr },
          ],
          note: 'Biển số này chưa tồn tại trong danh mục Xe Quen đã phê duyệt.',
        });

        sendEmailAlert(
          settings.email,
          `[SentriAI Alert] Xe lạ vào cổng: ${event.licensePlate}`,
          emailHtml,
          photoPath,
        ).catch((err) => console.warn('[NotificationService] Gate Email dispatch failed:', err));
      }
    } catch (err) {
      console.error('[NotificationService] Unexpected error in notifyGateStranger:', err);
    }
  }

  /**
   * Clear cooldowns (primarily for test suites)
   */
  public clearCooldowns(): void {
    cooldownMap.clear();
  }
}

export const notificationService = new NotificationService();
