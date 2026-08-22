/**
 * routes/upload.ts — User-Uploaded Media Registry & Storage API (VS-SETTINGS-LABEL)
 *
 * Implements persistent media storage exclusively for user-uploaded media files:
 * - GET    /api/v1/upload/media
 * - POST   /api/v1/upload/media
 * - DELETE /api/v1/upload/media/:id
 * - POST   /api/v1/upload/image (Legacy)
 */
import { Router, Request, Response, NextFunction } from 'express';
import path from 'path';
import fs from 'fs';
import { BadRequestError, NotFoundError } from '../utils/errors';
import { sendCreated, sendNoContent, sendSuccess } from '../utils/response';

const uploadRouter = Router();

// Base data directories
const baseDataDir = path.resolve(process.env.DATA_DIR || path.resolve(__dirname, '../../../data'));
const uploadsDir = path.join(baseDataDir, 'uploads');
const registryFile = path.join(baseDataDir, 'user_media.json');

fs.mkdirSync(uploadsDir, { recursive: true });

interface MediaItem {
  id: string;
  name: string;
  kind: 'img' | 'video';
  img: string;
  thumbnail?: string;
  filename: string;
  createdAt: string;
}

function loadRegistry(): MediaItem[] {
  try {
    if (fs.existsSync(registryFile)) {
      const content = fs.readFileSync(registryFile, 'utf-8');
      const items = JSON.parse(content);
      if (Array.isArray(items)) return items;
    }
  } catch (err) {
    console.warn('Error reading user_media.json registry:', err);
  }
  return [];
}

function saveRegistry(items: MediaItem[]) {
  try {
    fs.writeFileSync(registryFile, JSON.stringify(items, null, 2), 'utf-8');
  } catch (err) {
    console.warn('Error saving user_media.json registry:', err);
  }
}

/**
 * GET /api/v1/upload/media
 * Returns only user-uploaded media items.
 */
uploadRouter.get('/media', async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const items = loadRegistry();
    return sendSuccess(res, items);
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /api/v1/upload/media
 * Body: { data: string (base64 data URL), filename: string, kind?: 'img' | 'video', thumbnail?: string }
 */
uploadRouter.post('/media', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { data: rawData, filename: rawName, kind: explicitKind, thumbnail } = req.body;
    if (!rawData || typeof rawData !== 'string') {
      throw new BadRequestError('data field is required as a base64 data URI');
    }

    const matches = rawData.match(/^data:([A-Za-z0-9\/-]+);base64,(.+)$/);
    let mimeType = 'image/jpeg';
    let base64Data = rawData;

    if (matches && matches.length === 3) {
      mimeType = matches[1].toLowerCase();
      base64Data = matches[2];
    }

    const isVideo =
      explicitKind === 'video' ||
      mimeType.includes('video') ||
      mimeType.includes('mp4') ||
      mimeType.includes('webm');
    const kind: 'img' | 'video' = isVideo ? 'video' : 'img';

    const buffer = Buffer.from(base64Data, 'base64');
    const maxSize = isVideo ? 120 * 1024 * 1024 : 15 * 1024 * 1024;
    if (buffer.length > maxSize) {
      throw new BadRequestError(`File size exceeds limit (${isVideo ? '120MB' : '15MB'}).`);
    }

    let ext = isVideo ? '.mp4' : '.jpg';
    if (mimeType.includes('png')) ext = '.png';
    else if (mimeType.includes('webp')) ext = '.webp';
    else if (mimeType.includes('webm')) ext = '.webm';
    else if (mimeType.includes('mov') || mimeType.includes('quicktime')) ext = '.mov';

    const cleanBaseName = rawName
      ? path.basename(String(rawName).replace(/[^a-zA-Z0-9_.-]/g, '_'))
      : `media_${Date.now()}`;

    const filename = cleanBaseName.endsWith(ext) ? cleanBaseName : `${cleanBaseName}${ext}`;
    const targetFilePath = path.join(uploadsDir, filename);
    fs.writeFileSync(targetFilePath, buffer);

    const relativeUrl = `/data/uploads/${filename}`;
    const id = `user-media-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

    const newItem: MediaItem = {
      id,
      name: rawName && rawName.length > 22 ? `${rawName.slice(0, 18)}...` : rawName || filename,
      kind,
      img: relativeUrl,
      thumbnail: thumbnail || (kind === 'img' ? relativeUrl : undefined),
      filename,
      createdAt: new Date().toISOString(),
    };

    const currentItems = loadRegistry();
    const updated = [newItem, ...currentItems.filter((i) => i.filename !== filename)];
    saveRegistry(updated);

    return sendCreated(res, newItem);
  } catch (err) {
    return next(err);
  }
});

/**
 * DELETE /api/v1/upload/media/:idOrFilename
 */
uploadRouter.delete('/media/:idOrFilename', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const target = path.basename(req.params.idOrFilename);
    const currentItems = loadRegistry();

    const item = currentItems.find((i) => i.id === target || i.filename === target);
    if (item) {
      const filePath = path.join(uploadsDir, item.filename);
      if (fs.existsSync(filePath)) {
        try {
          fs.unlinkSync(filePath);
        } catch {}
      }
      const updated = currentItems.filter((i) => i.id !== item.id);
      saveRegistry(updated);
      return sendNoContent(res);
    }

    // If file exists on disk directly
    const directPath = path.join(uploadsDir, target);
    if (fs.existsSync(directPath)) {
      try {
        fs.unlinkSync(directPath);
      } catch {}
      const updated = currentItems.filter((i) => i.filename !== target);
      saveRegistry(updated);
      return sendNoContent(res);
    }

    throw new NotFoundError(`Không tìm thấy media ${target}`);
  } catch (err) {
    return next(err);
  }
});

/**
 * POST /api/v1/upload/image (Legacy support)
 */
uploadRouter.post('/image', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const rawImage = req.body.image || req.body.data;
    if (!rawImage || typeof rawImage !== 'string') {
      throw new BadRequestError('image field is required as a base64 string or data URI');
    }

    const matches = rawImage.match(/^data:([A-Za-z-+\/]+);base64,(.+)$/);
    let mimeType = 'image/jpeg';
    let base64Data = rawImage;

    if (matches && matches.length === 3) {
      mimeType = matches[1];
      base64Data = matches[2];
    }

    const buffer = Buffer.from(base64Data, 'base64');
    const ext = mimeType.includes('png') ? '.png' : mimeType.includes('webp') ? '.webp' : '.jpg';
    const filename = req.body.filename
      ? path.basename(String(req.body.filename).replace(/[^a-zA-Z0-9_.-]/g, '_'))
      : `upload_${Date.now()}${ext}`;

    const targetFilePath = path.join(uploadsDir, filename);
    fs.writeFileSync(targetFilePath, buffer);

    const relativePath = `/data/uploads/${filename}`;
    return sendCreated(res, {
      path: relativePath,
      url: relativePath,
      filename,
    });
  } catch (err) {
    return next(err);
  }
});

export { uploadRouter };
