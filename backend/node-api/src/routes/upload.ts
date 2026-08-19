/**
 * routes/upload.ts — Image and Media Upload REST API Router (VS-SETTINGS-LABEL)
 *
 * Implements file and base64 image upload for labeling and samples (M3, AC-06):
 * - POST /api/v1/upload/image
 */
import { Router, Request, Response, NextFunction } from 'express';
import path from 'path';
import fs from 'fs';
import { BadRequestError } from '../utils/errors';
import { sendCreated } from '../utils/response';
import { cropsDir } from '../index';

const uploadRouter = Router();

/**
 * POST /api/v1/upload/image
 * Body: { image: string (base64 or data URL), filename?: string }
 */
uploadRouter.post('/image', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const rawImage = req.body.image || req.body.data;
    if (!rawImage || typeof rawImage !== 'string') {
      throw new BadRequestError('image field is required as a base64 string or data URI');
    }

    // Parse base64 data
    const matches = rawImage.match(/^data:([A-Za-z-+\/]+);base64,(.+)$/);
    let mimeType = 'image/jpeg';
    let base64Data = rawImage;

    if (matches && matches.length === 3) {
      mimeType = matches[1];
      base64Data = matches[2];
    }

    const allowedMimeTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/jpg'];
    if (!allowedMimeTypes.includes(mimeType.toLowerCase())) {
      throw new BadRequestError('Invalid file type. Only JPEG, PNG, and WebP images are allowed.');
    }

    const buffer = Buffer.from(base64Data, 'base64');
    const maxSize = 10 * 1024 * 1024; // 10MB
    if (buffer.length > maxSize) {
      throw new BadRequestError('File size exceeds the 10MB limit.');
    }

    const ext = mimeType.includes('png') ? '.png' : mimeType.includes('webp') ? '.webp' : '.jpg';
    const filename = req.body.filename
      ? path.basename(String(req.body.filename).replace(/[^a-zA-Z0-9_.-]/g, '_'))
      : `upload_${Date.now()}_${Math.random().toString(36).substring(2, 8)}${ext}`;

    const labelsDir = path.resolve(cropsDir, '../labels');
    fs.mkdirSync(labelsDir, { recursive: true });

    const targetFilePath = path.join(labelsDir, filename);
    fs.writeFileSync(targetFilePath, buffer);

    const relativePath = `/data/labels/${filename}`;

    return sendCreated(res, {
      filename,
      path: relativePath,
      url: relativePath,
      sizeBytes: buffer.length,
      mimeType,
    });
  } catch (err) {
    return next(err);
  }
});

export { uploadRouter };
