import type {
  Vehicle,
  GateEvent,
  AreaEvent,
  PolygonZone
} from './types';

export const INITIAL_VEHICLES: Vehicle[] = [];

export const INITIAL_LABELS: Record<string, 'quen' | 'la'> = {};

export const INITIAL_GATE_EVENTS: GateEvent[] = [];

export const INITIAL_AREA_EVENTS: AreaEvent[] = [
  { id: 'ae1', time: '09:52', obj: 'Xe máy', zone: 'Zone cấm phương tiện cá nhân', st: 'Vi phạm', ok: false },
  { id: 'ae2', time: '09:38', obj: 'Xe nâng FL-02', zone: 'Zone bãi kiểm', st: 'Được phép', ok: true },
  { id: 'ae3', time: '09:12', obj: 'Xe container 15R-158.45', zone: 'Zone bãi kiểm', st: 'Được phép', ok: true },
  { id: 'ae4', time: '08:47', obj: 'Xe hơi trắng', zone: 'Zone bãi kiểm', st: 'Vi phạm', ok: false },
  { id: 'ae5', time: '08:20', obj: 'Xe nâng FL-01', zone: 'Zone bãi kiểm', st: 'Được phép', ok: true },
  { id: 'ae6', time: '07:55', obj: 'Xe container 15H-012.34', zone: 'Zone bãi kiểm', st: 'Được phép', ok: true }
];

export const INITIAL_ZONES: Record<string, PolygonZone[]> = {
  'GATE-01': [
    {
      id: 'zA',
      name: 'Làn IN 1',
      color: '#30d158',
      points: [[36, 54], [50, 54], [42, 95], [10, 95]],
      types: { 'Container': 1, 'Xe tải': 1, 'Xe con': 0, 'Xe máy': 0, 'Người': 0 }
    },
    {
      id: 'zB',
      name: 'Làn IN 2',
      color: '#2f9bff',
      points: [[52, 54], [66, 54], [95, 95], [47, 95]],
      types: { 'Container': 1, 'Xe tải': 1, 'Xe con': 0, 'Xe máy': 0, 'Người': 0 }
    }
  ],
  'BAI-KIEM': [
    {
      id: 'zK1',
      name: 'Zone bãi kiểm',
      color: '#30d158',
      points: [[54, 52], [88, 58], [92, 90], [48, 92]],
      types: { 'Container': 1, 'Xe nâng': 1, 'Xe tải': 1, 'Xe con': 0, 'Xe máy': 0, 'Xe đạp': 0, 'Người': 0 }
    },
    {
      id: 'zK2',
      name: 'Zone làn di chuyển',
      color: '#ff9f0a',
      points: [[38, 42], [52, 42], [46, 94], [8, 94]],
      types: { 'Container': 1, 'Xe nâng': 1, 'Xe tải': 1, 'Xe con': 0, 'Xe máy': 0, 'Xe đạp': 0, 'Người': 0 }
    },
    {
      id: 'zK3',
      name: 'Zone cấm PT cá nhân',
      color: '#ff453a',
      points: [[6, 30], [34, 28], [36, 60], [4, 66]],
      types: { 'Container': 1, 'Xe nâng': 0, 'Xe tải': 0, 'Xe con': 0, 'Xe máy': 0, 'Xe đạp': 0, 'Người': 0 }
    }
  ]
};
