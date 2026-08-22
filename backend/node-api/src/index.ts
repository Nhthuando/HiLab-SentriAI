/**
 * SentriAI — Node.js API Server
 * Entry point: Express REST API + WebSocket proxy
 * Port: 3001 (Architecture §6.1)
 */

import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';

// Load environment variables from backend/.env or root .env
const envPaths = [
  path.resolve(__dirname, '../../.env'),
  path.resolve(__dirname, '../.env'),
  path.resolve(process.cwd(), '.env'),
  path.resolve(process.cwd(), '../.env'),
];
for (const envPath of envPaths) {
  dotenv.config({ path: envPath });
}

import express from 'express';
import cors from 'cors';
import morgan from 'morgan';
import http from 'http';
import { setupWebSocketProxy } from './ws';
import { apiRouter } from './routes';
import { notFoundHandler } from './middleware/notFoundHandler';
import { errorHandler } from './middleware/errorHandler';

const app = express();
const PORT = Number(process.env.PORT ?? 3001);

// --- Middleware ---
app.use(cors({ origin: process.env.CORS_ORIGIN ?? 'http://localhost:5173' }));
if (process.env.NODE_ENV !== 'test') {
  app.use(morgan('dev'));
}
app.use(express.json({ limit: '150mb' }));
app.use(express.urlencoded({ limit: '150mb', extended: true }));

// --- Static Media Storage (Crops & Clips) ---
function resolveMediaDir(subDir: string): string {
  const configuredDir = process.env[subDir.toUpperCase() + '_DIR'];
  const backendDir = path.resolve(__dirname, '../..');
  const configuredMediaDir = configuredDir
    ? path.isAbsolute(configuredDir)
      ? configuredDir
      : path.resolve(backendDir, configuredDir)
    : undefined;
  const candidates = [
    configuredMediaDir,
    path.resolve(__dirname, '../../data', subDir),
    path.resolve(__dirname, '../data', subDir),
    path.resolve(process.cwd(), '../data', subDir),
    path.resolve(process.cwd(), 'data', subDir),
  ].filter(Boolean) as string[];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  const fallback = candidates[0] || path.resolve(process.cwd(), '../data', subDir);
  fs.mkdirSync(fallback, { recursive: true });
  return fallback;
}

const cropsDir = resolveMediaDir('crops');
const clipsDir = resolveMediaDir('clips');
const uploadsDir = resolveMediaDir('uploads');

app.use('/data/crops', express.static(cropsDir));
app.use('/data/clips', express.static(clipsDir));
app.use('/data/uploads', express.static(uploadsDir));

// --- REST API Version 1 Routes ---
app.use('/api/v1', apiRouter);

// --- 404 & Error Handling ---
app.use(notFoundHandler);
app.use(errorHandler);

// --- HTTP + WebSocket server ---
const server = http.createServer(app);

// Attach WebSocket Proxy (FDN-WS-PROXY)
setupWebSocketProxy(server);

// Only listen if not imported by test suites
if (process.env.NODE_ENV !== 'test') {
  server.listen(PORT, () => {
    console.log(`[SentriAI API] REST API listening on http://localhost:${PORT}/api/v1`);
    console.log(`[SentriAI WS] WebSocket proxy available on ws://localhost:${PORT}/ws/`);
  });
}

export { app, server, cropsDir, clipsDir };
