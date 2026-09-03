/**
 * pdfService.ts — PDF generation service using PDFKit for incident reports & shift handover summaries
 */
import fs from 'fs';
import path from 'path';
import PDFDocument from 'pdfkit';
import { prisma } from '../prisma/client';

function getUnicodeFontPath(): string | null {
  const candidates = [
    'C:\\Windows\\Fonts\\arial.ttf',
    'C:\\Windows\\Fonts\\Arial.ttf',
    'C:\\Windows\\Fonts\\times.ttf',
    'C:\\Windows\\Fonts\\segoeui.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/TTF/DejaVuSans.ttf',
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      return c;
    }
  }
  return null;
}

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

export class PdfService {
  private fontPath: string | null = getUnicodeFontPath();

  /**
   * Generates a PDF incident report for an Area Zone Violation
   */
  public async generateViolationPdf(violationId: string): Promise<Buffer> {
    const violation = await prisma.zoneViolation.findUnique({
      where: { id: violationId },
      include: { zone: true },
    });

    if (!violation) {
      throw new Error(`Violation event with ID ${violationId} not found.`);
    }

    return new Promise((resolve, reject) => {
      try {
        const doc = new PDFDocument({ size: 'A4', margin: 40 });
        const buffers: Buffer[] = [];

        doc.on('data', (chunk) => buffers.push(chunk));
        doc.on('end', () => resolve(Buffer.concat(buffers)));
        doc.on('error', (err) => reject(err));

        if (this.fontPath) {
          doc.font(this.fontPath);
        }

        // Header
        doc.fontSize(10).fillColor('#4b5563').text('HỆ THỐNG GIÁM SÁT AN NINH SENTRIAI', { align: 'center' });
        doc.fontSize(8).text('TRUNG TÂM KIỂM SOÁT AN NINH BÃI KIỂM & CỔNG', { align: 'center' });
        doc.moveDown(1);

        // Title
        doc
          .fontSize(16)
          .fillColor('#dc2626')
          .text('BIÊN BẢN GHI NHẬN SỰ CỐ VI PHẠM KHU VỰC', { align: 'center', underline: true });
        doc.moveDown(1.5);

        // Metadata box
        doc.fontSize(10).fillColor('#111827');
        const enteredDate = new Date(violation.enteredAt).toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' });
        const exitedDate = violation.exitedAt
          ? new Date(violation.exitedAt).toLocaleString('vi-VN', { timeZone: 'Asia/Bangkok' })
          : 'Chưa rời khỏi khu vực';
        const durationText = violation.durationSeconds !== null
          ? `${violation.durationSeconds} giây`
          : 'Đang tiếp diễn (OPEN)';

        doc.text(`• Mã sự cố (UUID): ${violation.id}`);
        doc.text(`• Vị trí Camera: ${violation.cameraId}`);
        doc.text(`• Khu vực vi phạm (Zone): ${violation.zone?.name || 'Khu vực bãi kiểm'}`);
        doc.text(`• Đối tượng phát hiện: ${violation.objectLabel}`);
        doc.text(`• Trạng thái xử lý: ${violation.status === 'OPEN' ? 'ĐANG VI PHẠM (Chưa giải quyết)' : 'ĐÃ KẾT THÚC'}`);
        doc.text(`• Thời điểm vào khu vực: ${enteredDate}`);
        doc.text(`• Thời điểm rời khu vực: ${exitedDate}`);
        doc.text(`• Tổng thời lượng vi phạm: ${durationText}`);
        doc.moveDown(1.5);

        // Visual snapshot
        const photoCandidate = (violation as any).cropPath || (violation as any).clipPath;
        const photoFile = resolveLocalMediaFile(photoCandidate);
        if (photoFile) {
          try {
            doc.fontSize(11).fillColor('#1f2937').text('HÌNH ẢNH BẰNG CHỨNG HIỆN TRƯỜNG:');
            doc.moveDown(0.5);
            doc.image(photoFile, {
              fit: [300, 200],
              align: 'center',
            });
            doc.moveDown(1);
          } catch {
            doc.fontSize(9).fillColor('#6b7280').text('(Không thể hiển thị định dạng ảnh này trong tài liệu)');
            doc.moveDown(1);
          }
        } else {
          doc.fontSize(9).fillColor('#6b7280').text('• Hình ảnh hiện trường: Đang lưu trữ trên hệ thống lưu trữ video.');
          doc.moveDown(1.5);
        }

        // Action & notes
        doc.fontSize(11).fillColor('#111827').text('KẾT LUẬN & ĐỀ XUẤT XỬ LÝ:');
        doc.moveDown(0.5);
        doc
          .fontSize(10)
          .fillColor('#374151')
          .text(
            'Phương tiện/đối tượng đã hoạt động không đúng quy định hoặc đi vào vùng giới hạn. Biên bản được lập tự động từ dữ liệu thị giác máy tính SentriAI để làm căn cứ xử lý vi phạm nội bộ.',
            { align: 'justify' },
          );
        doc.moveDown(2);

        // Signatures
        const currentY = doc.y;
        doc.fontSize(10).fillColor('#111827');
        doc.text('NGƯỜI VI PHẠM / LIÊN QUAN\n(Ký, ghi rõ họ tên)', 60, currentY, { align: 'center', width: 200 });
        doc.text('NHÂN VIÊN TRỰC BAN BẢO VỆ\n(Ký, ghi rõ họ tên)', 340, currentY, { align: 'center', width: 200 });

        doc.end();
      } catch (err) {
        reject(err);
      }
    });
  }

  /**
   * Generates a Shift Handover Report PDF from AI summary & stats
   */
  public async generateShiftReportPdf(params: {
    shiftName?: string;
    timeWindow?: string;
    summaryText: string;
    gateStats?: any;
    areaStats?: any;
  }): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      try {
        const doc = new PDFDocument({ size: 'A4', margin: 40 });
        const buffers: Buffer[] = [];

        doc.on('data', (chunk) => buffers.push(chunk));
        doc.on('end', () => resolve(Buffer.concat(buffers)));
        doc.on('error', (err) => reject(err));

        if (this.fontPath) {
          doc.font(this.fontPath);
        }

        // Header
        doc.fontSize(10).fillColor('#4b5563').text('HỆ THỐNG GIÁM SÁT AN NINH SENTRIAI', { align: 'center' });
        doc.fontSize(8).text('BÁO CÁO GIAO BAN VÀ TỔNG KẾT CA TRỰC AN NINH', { align: 'center' });
        doc.moveDown(1);

        const title = params.shiftName || 'BIÊN BẢN BÀN GIAO CA TRỰC';
        doc.fontSize(15).fillColor('#1d4ed8').text(title, { align: 'center', underline: true });
        if (params.timeWindow) {
          doc.fontSize(10).fillColor('#4b5563').text(`Khung giờ: ${params.timeWindow}`, { align: 'center' });
        }
        doc.moveDown(1.5);

        // Body Text from AI
        doc.fontSize(11).fillColor('#111827').text('NỘI DUNG TỔNG KẾT TỪ TRỢ LÝ SENTRIAI COPILOT:');
        doc.moveDown(0.5);

        // Clean markdown bold stars from AI text
        const cleanText = params.summaryText
          .replace(/\*\*(.*?)\*\*/g, '$1')
          .replace(/###?\s+/g, '')
          .trim();

        doc.fontSize(10).fillColor('#1f2937').text(cleanText, {
          align: 'left',
          lineGap: 3,
        });
        doc.moveDown(2);

        // Signatures
        const currentY = Math.min(doc.y, 700);
        doc.fontSize(10).fillColor('#111827');
        doc.text('NGƯỜI BÀN GIAO CA\n(Ký, ghi rõ họ tên)', 60, currentY, { align: 'center', width: 200 });
        doc.text('NGƯỜI NHẬN BÀN GIAO CA\n(Ký, ghi rõ họ tên)', 340, currentY, { align: 'center', width: 200 });

        doc.end();
      } catch (err) {
        reject(err);
      }
    });
  }
}

export const pdfService = new PdfService();
