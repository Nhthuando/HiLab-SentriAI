export type TabId = 'mon' | 'area' | 'set' | 'qa';
export type SettingsSubTab = 'label' | 'zone' | 'obj' | 'theme';
export type ThemeMode = 'dark' | 'light' | 'system';
export type AccentColor = 'blue' | 'emerald' | 'cyan' | 'purple' | 'amber';
export type VehicleStatus = 'quen' | 'la';
export type ObjectKind = 'xe' | 'nguoi';

export interface Vehicle {
  plate: string;
  type: string;
  visits: number;
  last: string;
  tint: string;
}

export interface GateEvent {
  id: string;
  time: string;
  plate: string;
  zone: string;
  conf: number | null;
  status: VehicleStatus;
  clipPath?: string | null;
  cropPath?: string | null;
  cameraId?: string;
  lane?: string;
  eventTimestamp?: string;
}

export type ViolationStatus = 'OPEN' | 'CLOSED';
export type AreaAction = 'STARTED' | 'ENDED';

export interface AreaViolationDto {
  id: string;
  cameraId: 'BAI-KIEM' | string;
  zoneId: string;
  zoneName: string;
  objectLabel: string;
  status: ViolationStatus;
  enteredAt: string;
  exitedAt: string | null;
  durationSeconds: number | null;
  clipUrl: string | null;
}

export interface AreaEventsPage {
  items: AreaViolationDto[];
  total: number;
  limit: number;
  offset: number;
}

export interface AreaZoneFeedDto {
  id: string;
  name: string;
  polygon: Array<{ x: number; y: number }> | Array<[number, number]>;
  ruleType: 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED' | string;
  targetLabels: string[];
}

export interface AreaDetectionDto {
  trackId: number | null;
  bbox: [number, number, number, number];
  normalized_bbox?: [number, number, number, number];
  class: string;
  label: string;
  confidence: number;
  status: 'VIOLATION' | 'ALLOWED' | 'OUTSIDE' | string;
  zoneMatches?: Array<{
    zoneId: string;
    zoneName: string;
    status: 'VIOLATION' | 'ALLOWED' | string;
  }>;
}

export interface AreaEvent {
  id: string;
  time: string;
  obj: string;
  zone: string;
  zoneId?: string;
  trackId?: number | null;
  source?: 'violation' | 'live_allowed';
  st: 'Được phép' | 'Vi phạm';
  ok: boolean;
  clipUrl?: string | null;
  durationSeconds?: number | null;
}

export interface PolygonZone {
  id: string;
  name: string;
  color: string;
  points: [number, number][]; // [x, y] percentages 0-100
  types: Record<string, number>; // 1 = allowed, 0 = forbidden
  ruleType?: 'PROHIBIT_SPECIFIED' | 'ALLOW_SPECIFIED';
  targetLabels?: string[];
}

export interface ObjectLabel {
  id: string;
  name: string;
  kind: ObjectKind;
  /** Canonical detector class used by the Python worker (for example `forklift`). */
  baseClass?: string;
  tint: string;
  samples: number;
}

export interface AnnotationSource {
  id: string;
  name: string;
  kind: 'img' | 'video';
  img?: string;
  thumbnail?: string;
  tint?: string;
  isDefault?: boolean;
  filename?: string;
}

export interface AnnotationSample {
  id: string;
  labelId: string;
  srcId: string;
  frame?: number | null;
  x: number;
  y: number;
  w: number;
  h: number;
  session?: number;
}

export interface TrainingReadiness {
  savedSamples: number;
  labelsWithSamples: number;
  sourceCount: number;
  excludedSamples: number;
  isReady: boolean;
  issues?: string[];
  labelCoverage?: Array<{
    label: string;
    minimumSamples: number;
    minimumSources: number;
    savedSamples: number;
    sourceCount: number;
    splitCounts: { train: number; val: number; test: number };
    ready: boolean;
  }>;
}

export type MockTrainingStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'paused_gpu'
  | 'evaluating'
  | 'candidate'
  | 'active'
  | 'failed';

export interface VideoClipInfo {
  cam: string;
  from: string;
  to: string;
  title: string;
  boxColor: string;
  boxLabel: string;
  tint: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  text: string;
  timestamp?: string;
  clip?: VideoClipInfo;
}

export interface FloatingNotification {
  id: string;
  title: string;
  message: string;
  zone: string;
  time: string;
  camId: string;
}
