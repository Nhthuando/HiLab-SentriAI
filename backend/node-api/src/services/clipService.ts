import fs from 'fs';
import path from 'path';
import type { PrismaClient } from '@prisma/client';
import { prisma } from '../prisma/client';

export type ClipEventType = 'gate' | 'violation' | 'activity';

export interface EventClipRecord {
  eventId: string;
  eventType: ClipEventType;
  cameraId: string;
  occurredAt: Date;
  videoTimecode?: string | null;
  label: string;
  title: string;
  clipPath: string | null;
}

export interface ClipReference {
  eventId: string;
  eventType: ClipEventType;
  cam: string;
  from: string;
  to: string;
  title: string;
  boxLabel: string;
  boxColor: string;
  tint: string;
  streamUrl: string;
  downloadUrl: string;
}

export type DeferredClipStatus = 'NOT_REQUESTED' | 'QUEUED' | 'GENERATING' | 'READY' | 'FAILED' | 'EXPIRED';

export interface ActivityEvidence {
  type: 'area_activity';
  eventId: string;
  title: string;
  cam: string;
  from: string;
  to: string;
  clipStatus: DeferredClipStatus;
  canRequestClip: boolean;
  clipId: string | null;
  message?: string;
}

export function getClipsDirectory(): string {
  // __dirname is node-api/src/services in ts-node and node-api/dist/services after build.
  const backendDir = path.resolve(__dirname, '../../..');
  const configured = process.env.CLIPS_DIR;
  return configured
    ? path.isAbsolute(configured) ? configured : path.resolve(backendDir, configured)
    : path.resolve(backendDir, 'data/clips');
}

export function resolveStoredClipPath(clipPath: string | null): string | null {
  if (!clipPath) return null;
  const fileName = path.basename(clipPath);
  if (!fileName || !fileName.toLowerCase().endsWith('.mp4')) return null;
  const root = path.resolve(getClipsDirectory());
  const candidate = path.resolve(root, fileName);
  if (path.dirname(candidate).toLowerCase() !== root.toLowerCase()) return null;
  try {
    return fs.statSync(candidate).isFile() ? candidate : null;
  } catch {
    return null;
  }
}

function secondsLabel(value: number): string {
  const seconds = ((value % 86400) + 86400) % 86400;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return [h, m, s].map((part) => String(part).padStart(2, '0')).join(':');
}

function parseTimecode(value?: string | null): number | null {
  if (!value) return null;
  const pieces = value.split(':').map(Number);
  if (pieces.some((piece) => !Number.isFinite(piece))) return null;
  if (pieces.length === 3) return pieces[0] * 3600 + pieces[1] * 60 + pieces[2];
  if (pieces.length === 2) return pieces[0] * 60 + pieces[1];
  return null;
}

function eventClock(record: EventClipRecord): { from: string; to: string } {
  const timecodeSeconds = parseTimecode(record.videoTimecode);
  if (timecodeSeconds !== null) {
    return { from: secondsLabel(timecodeSeconds), to: secondsLabel(timecodeSeconds + 10) };
  }
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Bangkok', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
  return { from: formatter.format(record.occurredAt), to: formatter.format(new Date(record.occurredAt.getTime() + 10_000)) };
}

export function buildClipReference(record: EventClipRecord): ClipReference | null {
  if (!resolveStoredClipPath(record.clipPath)) return null;
  const clock = eventClock(record);
  const eventPath = encodeURIComponent(record.eventId);
  return {
    eventId: record.eventId,
    eventType: record.eventType,
    cam: record.cameraId,
    from: clock.from,
    to: clock.to,
    title: record.title,
    boxLabel: record.label,
    boxColor: record.eventType === 'gate' ? '#f59e0b' : record.eventType === 'activity' ? '#22c55e' : '#ef4444',
    tint: record.eventType === 'gate' ? '#3f2b16' : record.eventType === 'activity' ? '#15351f' : '#3f1717',
    streamUrl: `/api/v1/clips/${eventPath}/stream`,
    downloadUrl: `/api/v1/clips/${eventPath}/download`,
  };
}

export async function findEventClipRecord(
  eventId: string,
  eventType?: ClipEventType,
  client: PrismaClient = prisma,
): Promise<EventClipRecord | null> {
  if (eventType !== 'violation') {
    const event = await client.gateEvent.findUnique({ where: { id: eventId } });
    if (event) {
      return {
        eventId: event.id, eventType: 'gate', cameraId: event.cameraId,
        occurredAt: event.eventTimestamp, videoTimecode: event.videoTimecode,
        label: event.licensePlate, title: `${event.licensePlate} · ${event.lane}`, clipPath: event.clipPath,
      };
    }
  }
  if (eventType !== 'gate') {
    const event = await client.zoneViolation.findUnique({ where: { id: eventId }, include: { zone: { select: { name: true } } } });
    if (event) {
      return {
        eventId: event.id, eventType: 'violation', cameraId: event.cameraId,
        occurredAt: event.enteredAt, label: event.objectLabel,
        title: `${event.objectLabel} · ${event.zone.name}`, clipPath: event.clipPath,
      };
    }
  }
  if (eventType === undefined || eventType === 'activity') {
    const event = await client.areaActivitySession.findUnique({ where: { id: eventId } });
    if (event) {
      return {
        eventId: event.id,
        eventType: 'activity',
        cameraId: event.cameraId,
        occurredAt: event.enteredAt,
        videoTimecode: event.sourcePositionSeconds === null
          ? null
          : secondsLabel(event.sourcePositionSeconds),
        label: event.objectLabel,
        title: `${event.objectLabel} · ${event.zoneName}`,
        clipPath: event.clipStatus === 'READY' ? event.clipPath : null,
      };
    }
  }
  return null;
}

export async function resolveActivityEvidence(
  eventId: string,
  client: PrismaClient = prisma,
): Promise<ActivityEvidence | undefined> {
  const activity = await client.areaActivitySession.findUnique({ where: { id: eventId } });
  if (!activity) return undefined;
  const violation = activity.violationId
    ? await client.zoneViolation.findUnique({ where: { id: activity.violationId } })
    : null;
  const rawStatus = String(violation?.clipStatus ?? activity.clipStatus ?? 'NOT_REQUESTED') as DeferredClipStatus;
  const clipId = violation?.id ?? activity.id;
  const clipPath = violation?.clipPath ?? activity.clipPath;
  const fileReady = rawStatus === 'READY' && Boolean(resolveStoredClipPath(clipPath));
  const status: DeferredClipStatus = rawStatus === 'READY' && !fileReady ? 'FAILED' : rawStatus;
  const clock = eventClock({
    eventId: activity.id,
    eventType: 'activity',
    cameraId: activity.cameraId,
    occurredAt: activity.enteredAt,
    videoTimecode: activity.sourcePositionSeconds === null ? null : secondsLabel(activity.sourcePositionSeconds),
    label: activity.objectLabel,
    title: `${activity.objectLabel} · ${activity.zoneName}`,
    clipPath,
  });
  return {
    type: 'area_activity',
    eventId: activity.id,
    title: `${activity.objectLabel} · ${activity.zoneName}`,
    cam: activity.cameraId,
    from: clock.from,
    to: clock.to,
    clipStatus: status,
    canRequestClip: Boolean(violation || activity.sourceKind !== 'UNAVAILABLE'),
    clipId: fileReady ? clipId : null,
    ...(status === 'FAILED' && rawStatus === 'READY'
      ? { message: 'File video đã tạo không còn tồn tại. Bạn có thể thử tạo lại.' }
      : activity.clipError ? { message: activity.clipError } : {}),
  };
}

export function serializeClipReference(clip: ClipReference | undefined): string | null {
  return clip ? `${clip.eventType}:${clip.eventId}` : null;
}

export function serializeChatReference(
  clip: ClipReference | undefined,
  evidence: ActivityEvidence | undefined,
): string | null {
  return evidence ? `activity:${evidence.eventId}` : serializeClipReference(clip);
}

export async function hydrateClipReference(token: string | null, client: PrismaClient = prisma): Promise<ClipReference | undefined> {
  if (!token) return undefined;
  const match = /^(gate|violation|activity):([0-9a-f-]{36})$/i.exec(token);
  if (!match) return undefined;
  const record = await findEventClipRecord(match[2], match[1].toLowerCase() as ClipEventType, client);
  return record ? buildClipReference(record) ?? undefined : undefined;
}

export async function hydrateChatReference(
  token: string | null,
  client: PrismaClient = prisma,
): Promise<{ clip?: ClipReference; evidence?: ActivityEvidence }> {
  if (token?.toLowerCase().startsWith('activity:')) {
    const match = /^activity:([0-9a-f-]{36})$/i.exec(token);
    return match ? { evidence: await resolveActivityEvidence(match[1], client) } : {};
  }
  return { clip: await hydrateClipReference(token, client) };
}
