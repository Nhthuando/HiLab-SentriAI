export type TabId = 'mon' | 'area' | 'set' | 'qa';
export type SettingsSubTab = 'label' | 'zone' | 'obj';
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
}

export interface AreaEvent {
  id: string;
  time: string;
  obj: string;
  zone: string;
  st: 'Được phép' | 'Vi phạm';
  ok: boolean;
}

export interface PolygonZone {
  id: string;
  name: string;
  color: string;
  points: [number, number][]; // [x, y] percentages 0-100
  types: Record<string, number>; // 1 = allowed, 0 = forbidden
}

export interface ObjectLabel {
  id: string;
  name: string;
  kind: ObjectKind;
  tint: string;
  samples: number;
}

export interface AnnotationSource {
  id: string;
  name: string;
  kind: 'img' | 'video';
  img?: string;
  tint?: string;
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
