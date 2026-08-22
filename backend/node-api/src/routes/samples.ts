/**
 * Annotation Samples REST API Router.
 * Persisted samples retain a verified source-media reference so only real uploaded
 * images and selected video frames can become training data.
 */
import fs from 'fs';
import path from 'path';
import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../prisma/client';
import { BadRequestError, NotFoundError } from '../utils/errors';
import { sendCreated, sendNoContent, sendSuccess } from '../utils/response';

const samplesRouter = Router();
const dataDir = path.resolve(__dirname, '../../../data');
const mediaRegistryPath = path.join(dataDir, 'user_media.json');

type MediaRecord = {
  id: string;
  kind: 'img' | 'video';
  filename: string;
  img: string;
};

function loadMediaRegistry(): MediaRecord[] {
  try {
    const parsed = JSON.parse(fs.readFileSync(mediaRegistryPath, 'utf8'));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function asNormalisedBbox(item: any): { x: number; y: number; w: number; h: number } | null {
  const raw = item.bbox || { x: item.x, y: item.y, w: item.w, h: item.h };
  const values = ['x', 'y', 'w', 'h'].map((key) => Number(raw?.[key]));
  if (!values.every(Number.isFinite)) return null;
  const [x, y, w, h] = values;
  // Canvas coordinates are percentages; stored training coordinates are normalised 0..1.
  const divisor = Math.max(x, y, w, h) > 1 ? 100 : 1;
  const box = { x: x / divisor, y: y / divisor, w: w / divisor, h: h / divisor };
  return box.x >= 0 && box.y >= 0 && box.w > 0 && box.h > 0 && box.x + box.w <= 1 && box.y + box.h <= 1 ? box : null;
}

samplesRouter.get('/', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const records = await prisma.labelSample.findMany({ orderBy: { createdAt: 'desc' }, take: 200 });
    return sendSuccess(res, records.map((record) => {
      const bbox = (record.bbox as any) || {};
      return {
        id: record.id,
        labelId: record.labelId,
        srcId: record.mediaRef || record.imagePath,
        x: Number(bbox.x ?? 0) * 100,
        y: Number(bbox.y ?? 0) * 100,
        w: Number(bbox.w ?? 0) * 100,
        h: Number(bbox.h ?? 0) * 100,
        frame: record.frameTimestampMs == null ? null : record.frameTimestampMs / 1000,
        session: 0,
      };
    }));
  } catch (error) { return next(error); }
});

samplesRouter.post('/batch', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const rawSamples = req.body?.samples;
    if (!Array.isArray(rawSamples) || rawSamples.length === 0) {
      throw new BadRequestError('samples must be a non-empty array');
    }

    const labelIds = Array.from(new Set(rawSamples.map((sample: any) => sample.labelId || sample.label_id).filter(Boolean)));
    const labels = await prisma.objectLabel.findMany({ where: { id: { in: labelIds } }, select: { id: true } });
    const labelIdsFound = new Set(labels.map((label) => label.id));
    const mediaById = new Map(loadMediaRegistry().map((media) => [media.id, media]));
    const data: Array<{ labelId: string; imagePath: string; mediaRef: string; mediaKind: string; frameTimestampMs: number | null; bbox: { x: number; y: number; w: number; h: number } }> = [];

    for (const item of rawSamples) {
      const labelId = item.labelId || item.label_id;
      if (!labelId || !labelIdsFound.has(labelId)) throw new BadRequestError('Nhãn đối tượng không tồn tại');

      const mediaRef = String(item.srcId || item.mediaRef || item.media_ref || '');
      const media = mediaById.get(mediaRef);
      if (!media) throw new BadRequestError('Mẫu phải dùng ảnh hoặc video đã import trong Cài đặt');

      const bbox = asNormalisedBbox(item);
      if (!bbox) throw new BadRequestError('Khung đánh dấu phải nằm trọn trong ảnh/video');

      const frameSeconds = item.frame == null ? null : Number(item.frame);
      const hasValidFrame = frameSeconds !== null && Number.isFinite(frameSeconds) && frameSeconds >= 0;
      if (media.kind === 'video' && !hasValidFrame) {
        throw new BadRequestError('Mẫu từ video phải có thời điểm khung hình hợp lệ');
      }
      if (media.kind === 'img' && frameSeconds != null) {
        throw new BadRequestError('Mẫu từ ảnh không được có thời điểm video');
      }

      data.push({
        labelId,
        imagePath: media.img,
        mediaRef: media.id,
        mediaKind: media.kind === 'video' ? 'VIDEO' : 'IMAGE',
        frameTimestampMs: media.kind === 'video' ? Math.round(frameSeconds! * 1000) : null,
        bbox,
      });
    }

    const result = await prisma.labelSample.createMany({ data });
    return sendCreated(res, { count: result.count, created: result.count });
  } catch (error) { return next(error); }
});

samplesRouter.delete('/:id', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const existing = await prisma.labelSample.findUnique({ where: { id: req.params.id } });
    if (!existing) throw new NotFoundError(`Không tìm thấy mẫu với id '${req.params.id}'`);
    await prisma.labelSample.delete({ where: { id: req.params.id } });
    return sendNoContent(res);
  } catch (error) { return next(error); }
});

export { samplesRouter };
