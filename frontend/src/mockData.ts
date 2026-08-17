import type {
  Vehicle,
  GateEvent,
  AreaEvent,
  PolygonZone,
  ObjectLabel,
  AnnotationSource,
  AnnotationSample,
  ChatMessage
} from './types';

export const INITIAL_VEHICLES: Vehicle[] = [
  { plate: '15R-158.45', type: 'Container', visits: 42, last: '16/08 08:42', tint: '#2a4a6b' },
  { plate: '16H-678.90', type: 'Xe tải', visits: 31, last: '16/08 07:15', tint: '#3d5a40' },
  { plate: '16L-998.21', type: 'Xe con', visits: 2, last: '16/08 09:18', tint: '#5a4a3d' },
  { plate: '29H-887.12', type: 'Xe tải', visits: 1, last: '15/08 22:04', tint: '#4a3d5a' },
  { plate: '15H-012.34', type: 'Container', visits: 27, last: '16/08 06:51', tint: '#2a4a6b' },
  { plate: '16K-345.67', type: 'Container', visits: 19, last: '16/08 05:33', tint: '#3d4a5a' }
];

export const INITIAL_LABELS: Record<string, 'quen' | 'la'> = {
  '15R-158.45': 'quen',
  '16H-678.90': 'quen',
  '16L-998.21': 'la',
  '29H-887.12': 'la',
  '15H-012.34': 'quen',
  '16K-345.67': 'quen'
};

export const INITIAL_GATE_EVENTS: GateEvent[] = [
  { id: 'ge1', time: '09:41', plate: '15R-158.45', zone: 'Làn IN 2', conf: 97, status: 'quen' },
  { id: 'ge2', time: '09:18', plate: '16L-998.21', zone: 'Làn IN 1', conf: 95, status: 'la' },
  { id: 'ge3', time: '08:56', plate: '15H-012.34', zone: 'Làn IN 1', conf: 98, status: 'quen' },
  { id: 'ge4', time: '08:42', plate: '15R-158.45', zone: 'Làn IN 2', conf: 96, status: 'quen' },
  { id: 'ge5', time: '08:11', plate: '—', zone: 'Làn IN 2', conf: null, status: 'la' },
  { id: 'ge6', time: '07:15', plate: '16H-678.90', zone: 'Làn IN 1', conf: 94, status: 'quen' },
  { id: 'ge7', time: '06:51', plate: '15H-012.34', zone: 'Làn IN 2', conf: 97, status: 'quen' },
  { id: 'ge8', time: '05:33', plate: '16K-345.67', zone: 'Làn IN 1', conf: 99, status: 'quen' }
];

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

export const INITIAL_OBJ_LABELS: ObjectLabel[] = [
  { id: 'l1', name: 'Container', kind: 'xe', tint: '#2a4a6b', samples: 128 },
  { id: 'l2', name: 'Xe tải', kind: 'xe', tint: '#3d5a40', samples: 64 },
  { id: 'l3', name: 'Xe nâng', kind: 'xe', tint: '#5a5230', samples: 41 },
  { id: 'l4', name: 'Xe cẩu', kind: 'xe', tint: '#4a3d5a', samples: 12 },
  { id: 'l5', name: 'Xe con', kind: 'xe', tint: '#5a4a3d', samples: 23 },
  { id: 'l6', name: 'Xe máy', kind: 'xe', tint: '#5a3d3d', samples: 17 },
  { id: 'l7', name: 'Xe đạp', kind: 'xe', tint: '#3d4a5a', samples: 6 },
  { id: 'l8', name: 'Người', kind: 'nguoi', tint: '#3d5a55', samples: 87 }
];

export const INITIAL_ANN_SOURCES: AnnotationSource[] = [
  { id: 'src1', name: 'baikiem-cam-01.jpg', kind: 'img', img: '/assets/cam-baikiem.png' },
  { id: 'src2', name: 'gate-lan-in-06-15.jpg', kind: 'img', img: '/assets/cam-gate.png' },
  { id: 'src3', name: 'yard-ca-chieu.mp4', kind: 'video', tint: '#3d4a3a' }
];

export const INITIAL_ANN_SAMPLES: AnnotationSample[] = [
  { id: 's1', labelId: 'l3', srcId: 'src1', x: 22, y: 40, w: 22, h: 40 },
  { id: 's2', labelId: 'l8', srcId: 'src1', x: 46, y: 44, w: 4.5, h: 9 }
];

export const INITIAL_QA_MESSAGES: ChatMessage[] = [
  {
    id: 'm0',
    role: 'ai',
    text: 'Xin chào! Tôi là Trợ lý AI SentriAI. Tôi có thể trả lời mọi câu hỏi về các sự kiện xe và phương tiện đã lưu trong hệ thống. Mỗi câu trả lời đều kèm trích dẫn đoạn video 10 giây làm bằng chứng.',
    timestamp: '09:50'
  }
];

export const QA_KNOWLEDGE_BASE = [
  {
    keys: ['bao nhiêu', 'xe lạ', 'lạ vào', 'xe la'],
    text: 'Hôm nay có 2 sự kiện xe lạ / vi phạm zone: 16L-998.21 (xe con, chưa gắn nhãn quen) bị phát hiện tại Làn IN 1 lúc 09:18, và 29H-887.12 (xe tải) vào Làn IN 2 lúc 08:11 — zone này chỉ cho phép container. Đoạn video sự kiện gần nhất bên dưới.',
    clip: {
      cam: 'GATE-01',
      from: '09:18:05',
      to: '09:18:15',
      title: '16L-998.21 · Xe lạ tại Làn IN 1',
      boxColor: '#ff453a',
      boxLabel: '16L-998.21 · XE LẠ',
      tint: '#5a4a3d'
    }
  },
  {
    keys: ['container', 'loại xe', 'loai xe'],
    text: 'Trong ngày có 5 lượt container vào zone hợp lệ (15R-158.45 ×2, 15H-012.34 ×2, 16K-345.67 ×1). Không có container nào vi phạm. Video lượt gần nhất lúc 09:41 bên dưới.',
    clip: {
      cam: 'GATE-01',
      from: '09:41:22',
      to: '09:41:32',
      title: '15R-158.45 · Container vào Làn IN 1',
      boxColor: '#30d158',
      boxLabel: '15R-158.45 · CHO PHÉP',
      tint: '#2a4a6b'
    }
  },
  {
    keys: ['sai loại', 'sai loai', 'bãi chờ', 'vi phạm', 'vi pham'],
    text: 'Có 1 sự kiện sai loại xe: 29H-887.12 (xe tải) đi vào Làn IN 2 lúc 08:11 — làn này cấu hình chỉ cho phép container. Hệ thống đã sinh cảnh báo và lưu clip 10s.',
    clip: {
      cam: 'GATE-01',
      from: '08:11:40',
      to: '08:11:50',
      title: '29H-887.12 · Sai loại xe tại Làn IN 2',
      boxColor: '#ff9f0a',
      boxLabel: '29H-887.12 · SAI LOẠI',
      tint: '#4a3d5a'
    }
  },
  {
    keys: ['xe máy', 'xe may', 'xe đạp', 'xe dap', 'xe hơi', 'xe hoi', 'khu vực', 'khu vuc', 'cá nhân', 'ca nhan'],
    text: 'Trong khu vực bãi hôm nay có 2 vi phạm loại xe: 1 xe máy vào Zone cấm phương tiện cá nhân lúc 09:52 và 1 xe hơi trắng vào Zone bãi container lúc 08:47. Xe nâng và xe container hoạt động bình thường (4 lượt hợp lệ). Video vi phạm gần nhất bên dưới.',
    clip: {
      cam: 'BAI-KIEM',
      from: '09:52:18',
      to: '09:52:28',
      title: 'Xe máy · Vi phạm Zone cấm phương tiện cá nhân',
      boxColor: '#ff453a',
      boxLabel: 'XE MÁY · VI PHẠM',
      tint: '#5a3d3d'
    }
  },
  {
    keys: ['xe nâng', 'xe nang', 'forklift'],
    text: 'Xe nâng thuộc nhóm được phép trong Zone bãi container. Hôm nay ghi nhận 2 lượt hoạt động: FL-01 lúc 08:20 và FL-02 lúc 09:38 — đều hợp lệ, không có cảnh báo. Video lượt gần nhất bên dưới.',
    clip: {
      cam: 'BAI-KIEM',
      from: '09:38:02',
      to: '09:38:12',
      title: 'Xe nâng FL-02 · Zone bãi container',
      boxColor: '#30d158',
      boxLabel: 'XE NÂNG · ĐƯỢC PHÉP',
      tint: '#5a5230'
    }
  },
  {
    keys: ['15r', '158', '158.45'],
    text: 'Xe 15R-158.45 (container, nhãn: xe quen) vào cổng 2 lần hôm nay: 08:42 vào Làn IN 2 và 09:41 vào Làn IN 1 — cả hai lượt đều hợp lệ. Video lượt 09:41 bên dưới.',
    clip: {
      cam: 'GATE-01',
      from: '09:41:22',
      to: '09:41:32',
      title: '15R-158.45 · Lượt vào 09:41',
      boxColor: '#30d158',
      boxLabel: '15R-158.45 · CHO PHÉP',
      tint: '#2a4a6b'
    }
  }
];

export const QA_FALLBACK = {
  text: 'Tôi tìm thấy 8 sự kiện trong ngày: 6 lượt hợp lệ, 2 cảnh báo (1 xe lạ, 1 sai loại xe). Bạn có thể hỏi cụ thể hơn — ví dụ theo biển số (vd: "15R-158.45"), theo zone, hoặc theo loại vi phạm. Video sự kiện mới nhất bên dưới.',
  clip: {
    cam: 'GATE-01',
    from: '09:41:22',
    to: '09:41:32',
    title: 'Sự kiện gần nhất · 15R-158.45 vào Làn IN 1',
    boxColor: '#30d158',
    boxLabel: '15R-158.45 · CHO PHÉP',
    tint: '#2a4a6b'
  }
};
