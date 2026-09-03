/**
 * emailService.ts — Dispatches incident alerts and summaries via SMTP email (Nodemailer)
 */
import fs from 'fs';
import path from 'path';
import nodemailer from 'nodemailer';
import type { EmailConfig } from './notificationConfigService';

export interface EmailSendResult {
  success: boolean;
  messageId?: string;
  error?: string;
}

export function createEmailTransporter(config: EmailConfig) {
  return nodemailer.createTransport({
    host: config.smtpHost,
    port: config.smtpPort,
    secure: config.smtpSecure,
    auth: {
      user: config.smtpUser,
      pass: config.smtpPass,
    },
    tls: {
      rejectUnauthorized: false,
    },
  });
}

export function renderAlertEmailHtml(params: {
  title: string;
  badgeText: string;
  badgeColor?: string;
  details: { label: string; value: string }[];
  note?: string;
}): string {
  const badgeColor = params.badgeColor || '#e63946';
  const detailRows = params.details
    .map(
      (d) => `
      <tr>
        <td style="padding: 8px 12px; font-weight: 600; color: #4a5568; width: 35%; border-bottom: 1px solid #edf2f7;">${d.label}</td>
        <td style="padding: 8px 12px; color: #1a202c; border-bottom: 1px solid #edf2f7;">${d.value}</td>
      </tr>`,
    )
    .join('');

  return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>${params.title}</title>
</head>
<body style="margin: 0; padding: 24px; background-color: #0d1117; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <div style="max-width: 600px; margin: 0 auto; background: #161b22; border: 1px solid #30363d; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
    <div style="background: linear-gradient(135deg, #1f2937, #111827); padding: 20px 24px; border-bottom: 1px solid #30363d; display: flex; align-items: center; justify-content: space-between;">
      <h2 style="margin: 0; color: #58a6ff; font-size: 20px; letter-spacing: 0.5px;">SentriAI System Alert</h2>
      <span style="display: inline-block; background-color: ${badgeColor}; color: #ffffff; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; text-transform: uppercase;">
        ${params.badgeText}
      </span>
    </div>
    <div style="padding: 24px;">
      <h3 style="margin-top: 0; margin-bottom: 16px; color: #f0f6fc; font-size: 17px;">${params.title}</h3>
      <table style="width: 100%; border-collapse: collapse; background: #0d1117; border-radius: 8px; overflow: hidden; margin-bottom: 20px; font-size: 14px;">
        <tbody>
          ${detailRows}
        </tbody>
      </table>
      ${
        params.note
          ? `<p style="margin: 0 0 20px 0; padding: 12px; background: rgba(234, 179, 8, 0.1); border-left: 4px solid #eab308; color: #eab308; font-size: 13px; border-radius: 4px;">${params.note}</p>`
          : ''
      }
      <div style="text-align: center; margin-top: 24px; padding-top: 16px; border-top: 1px solid #30363d;">
        <p style="margin: 0; color: #8b949e; font-size: 12px;">
          Thông báo được gửi tự động từ Hệ thống Giám sát An ninh SentriAI.<br>
          Thời gian: ${new Date().toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' })}
        </p>
      </div>
    </div>
  </div>
</body>
</html>`;
}

export async function sendEmailAlert(
  config: EmailConfig,
  subject: string,
  htmlBody: string,
  attachmentPath?: string | null,
): Promise<EmailSendResult> {
  if (!config.enabled) {
    return { success: false, error: 'Email service is disabled in settings.' };
  }
  if (!config.smtpUser || !config.smtpPass || !config.toEmails || config.toEmails.length === 0) {
    return { success: false, error: 'Missing SMTP credentials or recipient emails.' };
  }

  try {
    const transporter = createEmailTransporter(config);

    const mailOptions: nodemailer.SendMailOptions = {
      from: `"SentriAI Alert" <${config.fromEmail || config.smtpUser}>`,
      to: config.toEmails.join(', '),
      subject,
      html: htmlBody,
    };

    if (attachmentPath && fs.existsSync(attachmentPath)) {
      mailOptions.attachments = [
        {
          filename: path.basename(attachmentPath),
          path: attachmentPath,
        },
      ];
    }

    const info = await transporter.sendMail(mailOptions);
    return { success: true, messageId: info.messageId };
  } catch (err: any) {
    console.error('[EmailService] Failed to send email:', err.message);
    return { success: false, error: err.message };
  }
}

export async function testEmailConnection(config: EmailConfig): Promise<EmailSendResult> {
  const testSubject = '[SentriAI] Kiểm tra kết nối Email Thông báo thành công';
  const html = renderAlertEmailHtml({
    title: 'Xác thực Hệ thống Email SentriAI',
    badgeText: 'TEST OK',
    badgeColor: '#22c55e',
    details: [
      { label: 'Trạng thái', value: 'Kết nối SMTP thành công' },
      { label: 'Máy chủ SMTP', value: `${config.smtpHost}:${config.smtpPort}` },
      { label: 'Tài khoản gửi', value: config.smtpUser },
      { label: 'Danh sách nhận', value: config.toEmails.join(', ') || 'Chưa cấu hình' },
      {
        label: 'Thời điểm kiểm tra',
        value: new Date().toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' }),
      },
    ],
    note: 'Hệ thống đã sẵn sàng gửi thông báo sự cố và biên bản vi phạm tới hòm thư này.',
  });

  return sendEmailAlert(config, testSubject, html);
}
