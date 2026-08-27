import type { FunctionDeclaration } from '@google/genai';
import { Type } from '@google/genai';
import type { Prisma, PrismaClient } from '@prisma/client';
import { prisma } from '../prisma/client';
import {
  buildClipReference,
  findEventClipRecord,
  type ClipReference,
  resolveActivityEvidence,
  type ActivityEvidence,
} from '../services/clipService';

const MAX_TOOL_ROWS = 50;
const APP_TIME_ZONE = 'Asia/Bangkok';

export interface QaToolExecution {
  name: string;
  result: Record<string, unknown>;
  clips: ClipReference[];
  evidence?: ActivityEvidence;
}

export const QA_TOOL_DECLARATIONS: FunctionDeclaration[] = [
  {
    name: 'get_stranger_vehicles_today',
    description: 'Đếm và liệt kê xe lạ vào cổng hôm nay theo múi giờ Asia/Bangkok.',
    parameters: { type: Type.OBJECT, properties: {} },
  },
  {
    name: 'get_known_vehicles_today',
    description: 'Đếm và liệt kê xe quen vào cổng hôm nay theo múi giờ Asia/Bangkok.',
    parameters: { type: Type.OBJECT, properties: {} },
  },
  {
    name: 'get_gate_events_by_plate',
    description: 'Tra cứu các sự kiện cổng đã lưu theo biển số xe.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        plate: { type: Type.STRING, description: 'Biển số xe cần tra cứu.' },
      },
      required: ['plate'],
    },
  },
  {
    name: 'get_violations_by_zone',
    description: 'Tra cứu các vi phạm đã lưu theo tên khu vực/zone và tùy chọn loại đối tượng.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        zoneName: { type: Type.STRING, description: 'Tên hoặc một phần tên zone.' },
        objectLabel: { type: Type.STRING, description: 'Tên loại đối tượng, nếu người dùng nêu rõ.' },
      },
      required: ['zoneName'],
    },
  },
  {
    name: 'get_violations_today',
    description: 'Đếm và liệt kê vi phạm hôm nay, có thể lọc theo loại đối tượng.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        objectLabel: { type: Type.STRING, description: 'Tên loại đối tượng, nếu cần lọc.' },
      },
    },
  },
  {
    name: 'get_area_activity_summary',
    description: 'Thống kê các lượt đối tượng đi vào zone BAI-KIEM hôm nay, gồm số lượt, thời lượng, zone và hợp lệ/vi phạm.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        objectLabel: { type: Type.STRING, description: 'Tên tiếng Việt, ví dụ Xe nâng hoặc Người.' },
        canonicalClass: { type: Type.STRING, description: 'Canonical detector class nếu biết, ví dụ forklift.' },
        zoneName: { type: Type.STRING, description: 'Tên hoặc một phần tên zone.' },
        policyResult: { type: Type.STRING, enum: ['ALLOWED', 'VIOLATION'], description: 'Lọc lượt hợp lệ hoặc vi phạm.' },
      },
    },
  },
  {
    name: 'get_area_activity_sessions',
    description: 'Liệt kê các phiên hoạt động BAI-KIEM hôm nay với giờ vào/ra và thời lượng.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        objectLabel: { type: Type.STRING },
        canonicalClass: { type: Type.STRING },
        zoneName: { type: Type.STRING },
        policyResult: { type: Type.STRING, enum: ['ALLOWED', 'VIOLATION'] },
      },
    },
  },
  {
    name: 'get_current_area_activity',
    description: 'Liệt kê các đối tượng có phiên OPEN đang được ghi nhận trong zone BAI-KIEM.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        objectLabel: { type: Type.STRING },
        canonicalClass: { type: Type.STRING },
        zoneName: { type: Type.STRING },
        policyResult: { type: Type.STRING, enum: ['ALLOWED', 'VIOLATION'] },
      },
    },
  },
  {
    name: 'get_clip_reference',
    description: 'Lấy tham chiếu clip đã lưu cho một event UUID do tool khác trả về.',
    parameters: {
      type: Type.OBJECT,
      properties: {
        eventId: { type: Type.STRING, description: 'UUID của gate event hoặc zone violation.' },
        eventType: {
          type: Type.STRING,
          enum: ['gate', 'violation', 'activity'],
          description: 'Loại sự kiện, nếu đã biết.',
        },
      },
      required: ['eventId'],
    },
  },
];

function textArg(args: Record<string, unknown>, key: string, required = false): string | undefined {
  const value = args[key];
  if (value === undefined || value === null) {
    if (required) throw new Error(`Missing required tool argument: ${key}`);
    return undefined;
  }
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`Invalid tool argument: ${key}`);
  }
  return value.trim();
}

function activityWhere(
  args: Record<string, unknown>,
  range?: { start: Date; end: Date },
): Prisma.AreaActivitySessionWhereInput {
  const objectLabel = textArg(args, 'objectLabel');
  const canonicalClass = textArg(args, 'canonicalClass');
  const zoneName = textArg(args, 'zoneName');
  const policyResult = textArg(args, 'policyResult');
  if (policyResult && policyResult !== 'ALLOWED' && policyResult !== 'VIOLATION') {
    throw new Error('Invalid tool argument: policyResult');
  }
  return {
    cameraId: 'BAI-KIEM',
    ...(range ? { enteredAt: { gte: range.start, lt: range.end } } : {}),
    ...(objectLabel ? { objectLabel: { contains: objectLabel, mode: 'insensitive' } } : {}),
    ...(canonicalClass ? { canonicalClass: { equals: canonicalClass, mode: 'insensitive' } } : {}),
    ...(zoneName ? { zoneName: { contains: zoneName, mode: 'insensitive' } } : {}),
    ...(policyResult ? { policyResult } : {}),
  };
}

function activityDetail(row: {
  id: string; cameraId: string; zoneName: string; objectLabel: string; canonicalClass: string;
  policyResult: string; sessionStatus: string; enteredAt: Date; exitedAt: Date | null;
  durationSeconds: number | null;
}, now: Date): Record<string, unknown> {
  const durationSeconds = row.durationSeconds ?? Math.max(0, Math.floor((now.getTime() - row.enteredAt.getTime()) / 1000));
  return {
    id: row.id,
    cameraId: row.cameraId,
    zoneName: row.zoneName,
    objectLabel: row.objectLabel,
    canonicalClass: row.canonicalClass,
    policyResult: row.policyResult,
    sessionStatus: row.sessionStatus,
    enteredAtLocal: formatLocalDateTime(row.enteredAt),
    exitedAtLocal: row.exitedAt ? formatLocalDateTime(row.exitedAt) : null,
    durationSeconds,
    durationProvisional: row.sessionStatus === 'OPEN',
  };
}

export function todayRange(now = new Date()): { start: Date; end: Date } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: APP_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value);
  const start = new Date(Date.UTC(value('year'), value('month') - 1, value('day')) - 7 * 60 * 60 * 1000);
  return { start, end: new Date(start.getTime() + 24 * 60 * 60 * 1000) };
}

function formatLocalDateTime(value: Date): string {
  return `${new Intl.DateTimeFormat('vi-VN', {
    timeZone: APP_TIME_ZONE,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(value)} UTC+07:00`;
}

async function gateEventsByStatus(
  status: 'KNOWN' | 'STRANGER',
  client: PrismaClient,
): Promise<QaToolExecution> {
  const range = todayRange();
  const where = { status, eventTimestamp: { gte: range.start, lt: range.end } };
  const [count, rows] = await Promise.all([
    client.gateEvent.count({ where }),
    client.gateEvent.findMany({ where, orderBy: { eventTimestamp: 'desc' }, take: MAX_TOOL_ROWS }),
  ]);
  const clips: ClipReference[] = [];
  const events = rows.map((row) => {
    const clip = buildClipReference({
      eventId: row.id,
      eventType: 'gate',
      cameraId: row.cameraId,
      occurredAt: row.eventTimestamp,
      videoTimecode: row.videoTimecode,
      label: row.licensePlate,
      title: `${row.licensePlate} · ${row.lane}`,
      clipPath: row.clipPath,
    });
    if (clip) clips.push(clip);
    return {
      id: row.id,
      cameraId: row.cameraId,
      lane: row.lane,
      licensePlate: row.licensePlate,
      status: row.status,
      confidence: row.confidence,
      timestampLocal: formatLocalDateTime(row.eventTimestamp),
      clipAvailable: Boolean(clip),
    };
  });
  return { name: status === 'STRANGER' ? 'get_stranger_vehicles_today' : 'get_known_vehicles_today', result: { count, events }, clips };
}

export async function executeQaTool(
  name: string,
  args: Record<string, unknown> = {},
  client: PrismaClient = prisma,
): Promise<QaToolExecution> {
  if (name === 'get_stranger_vehicles_today') return gateEventsByStatus('STRANGER', client);
  if (name === 'get_known_vehicles_today') return gateEventsByStatus('KNOWN', client);

  if (name === 'get_area_activity_summary' || name === 'get_area_activity_sessions' || name === 'get_current_area_activity') {
    const now = new Date();
    const range = name === 'get_current_area_activity' ? undefined : todayRange(now);
    const where: Prisma.AreaActivitySessionWhereInput = {
      ...activityWhere(args, range),
      ...(name === 'get_current_area_activity' ? { sessionStatus: 'OPEN' } : {}),
    };
    const take: number = name === 'get_area_activity_summary' ? 5000 : MAX_TOOL_ROWS;
    const rows = await client.areaActivitySession.findMany({
      where,
      orderBy: [{ enteredAt: 'desc' }, { id: 'desc' }],
      take,
    });
    const coverage = await client.areaActivityCollectionState.findUnique({
      where: { cameraId: 'BAI-KIEM' },
    });
    const details = rows.map((row) => activityDetail(row, now));
    const evidence = rows.length ? await resolveActivityEvidence(rows[0].id, client) : undefined;
    const coverageResult = coverage ? {
      collectionStartedAtLocal: formatLocalDateTime(coverage.startedAt),
      lastObservedAtLocal: formatLocalDateTime(coverage.lastObservedAt),
      isStale: now.getTime() - coverage.lastObservedAt.getTime() > 2 * 60 * 1000,
    } : null;

    if (name === 'get_area_activity_summary') {
      const durations = details.map((item) => Number(item.durationSeconds));
      const byZone: Record<string, number> = {};
      for (const row of rows) byZone[row.zoneName] = (byZone[row.zoneName] ?? 0) + 1;
      const totalObservedSeconds = durations.reduce((sum, value) => sum + value, 0);
      return {
        name,
        result: {
          summary: {
            entrySessions: rows.length,
            completedExits: rows.filter((row) => row.sessionStatus === 'CLOSED').length,
            openSessions: rows.filter((row) => row.sessionStatus === 'OPEN').length,
            totalObservedSeconds,
            averageSeconds: rows.length ? Math.round(totalObservedSeconds / rows.length) : 0,
            maximumSeconds: durations.length ? Math.max(...durations) : 0,
            allowedSessions: rows.filter((row) => row.policyResult === 'ALLOWED').length,
            violationSessions: rows.filter((row) => row.policyResult === 'VIOLATION').length,
            byZone,
            firstEntryLocal: rows.length ? formatLocalDateTime(rows[rows.length - 1].enteredAt) : null,
            latestEntryLocal: rows.length ? formatLocalDateTime(rows[0].enteredAt) : null,
          },
          queryWindow: range ? { start: range.start.toISOString(), end: range.end.toISOString(), timeZone: APP_TIME_ZONE } : null,
          coverage: coverageResult,
          recentSessions: details.slice(0, 10),
        },
        clips: [],
        ...(evidence ? { evidence } : {}),
      };
    }
    return {
      name,
      result: { count: rows.length, sessions: details, coverage: coverageResult },
      clips: [],
      ...(evidence ? { evidence } : {}),
    };
  }

  if (name === 'get_gate_events_by_plate') {
    const plate = textArg(args, 'plate', true)!.toUpperCase().replace(/\s+/g, '');
    const rows = await client.gateEvent.findMany({
      where: { licensePlate: { equals: plate, mode: 'insensitive' } },
      orderBy: { eventTimestamp: 'desc' },
      take: MAX_TOOL_ROWS,
    });
    const clips: ClipReference[] = [];
    const events = rows.map((row) => {
      const clip = buildClipReference({
        eventId: row.id,
        eventType: 'gate',
        cameraId: row.cameraId,
        occurredAt: row.eventTimestamp,
        videoTimecode: row.videoTimecode,
        label: row.licensePlate,
        title: `${row.licensePlate} · ${row.lane}`,
        clipPath: row.clipPath,
      });
      if (clip) clips.push(clip);
      return {
        id: row.id,
        cameraId: row.cameraId,
        lane: row.lane,
        licensePlate: row.licensePlate,
        status: row.status,
        timestampLocal: formatLocalDateTime(row.eventTimestamp),
        clipAvailable: Boolean(clip),
      };
    });
    return { name, result: { count: events.length, events }, clips };
  }

  if (name === 'get_violations_by_zone' || name === 'get_violations_today') {
    const zoneName = name === 'get_violations_by_zone' ? textArg(args, 'zoneName', true) : undefined;
    const objectLabel = textArg(args, 'objectLabel');
    const range = name === 'get_violations_today' ? todayRange() : undefined;
    const where = {
      ...(range ? { enteredAt: { gte: range.start, lt: range.end } } : {}),
      ...(zoneName ? { zone: { name: { contains: zoneName, mode: 'insensitive' as const } } } : {}),
      ...(objectLabel ? { objectLabel: { contains: objectLabel, mode: 'insensitive' as const } } : {}),
    };
    const [count, rows] = await Promise.all([
      client.zoneViolation.count({ where }),
      client.zoneViolation.findMany({
        where,
        include: { zone: { select: { name: true } } },
        orderBy: { enteredAt: 'desc' },
        take: MAX_TOOL_ROWS,
      }),
    ]);
    const clips: ClipReference[] = [];
    const violations = rows.map((row) => {
      const clip = buildClipReference({
        eventId: row.id,
        eventType: 'violation',
        cameraId: row.cameraId,
        occurredAt: row.enteredAt,
        label: row.objectLabel,
        title: `${row.objectLabel} · ${row.zone.name}`,
        clipPath: row.clipPath,
      });
      if (clip) clips.push(clip);
      return {
        id: row.id,
        cameraId: row.cameraId,
        zoneName: row.zone.name,
        objectLabel: row.objectLabel,
        status: row.status,
        enteredAtLocal: formatLocalDateTime(row.enteredAt),
        exitedAtLocal: row.exitedAt ? formatLocalDateTime(row.exitedAt) : null,
        durationSeconds: row.durationSeconds,
        clipAvailable: Boolean(clip),
      };
    });
    return { name, result: { count, violations }, clips };
  }

  if (name === 'get_clip_reference') {
    const eventId = textArg(args, 'eventId', true)!;
    const rawEventType = textArg(args, 'eventType');
    const eventType = rawEventType === 'gate' || rawEventType === 'violation' || rawEventType === 'activity' ? rawEventType : undefined;
    if (eventType === 'activity') {
      const evidence = await resolveActivityEvidence(eventId, client);
      return { name, result: evidence ? { found: true, evidence } : { found: false, message: 'Không có dữ liệu hoạt động' }, clips: [], ...(evidence ? { evidence } : {}) };
    }
    const record = await findEventClipRecord(eventId, eventType, client);
    const clip = record ? buildClipReference(record) : null;
    return { name, result: clip ? { found: true, clip } : { found: false, message: 'Không có clip' }, clips: clip ? [clip] : [] };
  }

  throw new Error(`Unsupported QA tool: ${name}`);
}
