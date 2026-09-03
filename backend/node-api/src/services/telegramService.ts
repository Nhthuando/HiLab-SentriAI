/**
 * telegramService.ts — Dispatches real-time alerts and snapshots to Telegram Bot
 */
import fs from 'fs';
import path from 'path';

export interface TelegramSendResult {
  success: boolean;
  messageId?: number;
  error?: string;
}

export async function sendTelegramMessage(
  botToken: string,
  chatId: string,
  htmlText: string,
  photoPath?: string | null,
): Promise<TelegramSendResult> {
  if (!botToken || !chatId) {
    return { success: false, error: 'Telegram botToken or chatId is missing.' };
  }

  const cleanToken = botToken.trim();
  const cleanChatId = chatId.trim();

  // If photo is provided and exists on disk, use sendPhoto
  if (photoPath && fs.existsSync(photoPath)) {
    try {
      const fileBuffer = fs.readFileSync(photoPath);
      const fileName = path.basename(photoPath);
      const blob = new Blob([fileBuffer]);

      const formData = new FormData();
      formData.append('chat_id', cleanChatId);
      formData.append('caption', htmlText);
      formData.append('parse_mode', 'HTML');
      formData.append('photo', blob, fileName);

      const res = await fetch(`https://api.telegram.org/bot${cleanToken}/sendPhoto`, {
        method: 'POST',
        body: formData,
      });

      const data = (await res.json()) as any;
      if (data.ok) {
        return { success: true, messageId: data.result?.message_id };
      }
      console.warn('[TelegramService] sendPhoto failed, falling back to sendMessage:', data.description);
    } catch (err: any) {
      console.warn('[TelegramService] Error in sendPhoto, falling back to sendMessage:', err.message);
    }
  }

  // Fallback to text sendMessage
  try {
    const res = await fetch(`https://api.telegram.org/bot${cleanToken}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: cleanChatId,
        text: htmlText,
        parse_mode: 'HTML',
        disable_web_page_preview: false,
      }),
    });

    const data = (await res.json()) as any;
    if (data.ok) {
      return { success: true, messageId: data.result?.message_id };
    }
    return { success: false, error: data.description || 'Telegram API error' };
  } catch (err: any) {
    return { success: false, error: err.message };
  }
}

export async function testTelegramConnection(
  botToken: string,
  chatId: string,
): Promise<TelegramSendResult> {
  const testMsg =
    `🔔 <b>[SentriAI] Kiểm tra kết nối Telegram Bot thành công!</b>\n\n` +
    `Hệ thống giám sát SentriAI đã kết nối thành công với nhóm/kênh này.\n` +
    `Thời gian: <code>${new Date().toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' })}</code>\n` +
    `Trạng thái: 🟢 <b>Sẵn sàng nhận cảnh báo</b>`;

  return sendTelegramMessage(botToken, chatId, testMsg);
}
