import assert from 'node:assert/strict';
import {
  ZoneValidationError,
  parseCreateZoneInput,
  parsePolygonPoints,
  parseUpdateZoneInput,
} from '../routes/zones';

function expectValidationError(action: () => unknown): void {
  assert.throws(action, ZoneValidationError);
}

const polygon = [
  { x: 0.1, y: 0.1 },
  { x: 0.8, y: 0.1 },
  { x: 0.5, y: 0.8 },
];

const created = parseCreateZoneInput({
  cameraId: 'BAI-KIEM',
  name: '  Vùng kiểm thử  ',
  polygonPoints: polygon,
  ruleType: 'ALLOW_SPECIFIED',
  targetLabels: ['Người', 'Container', 'người'],
  isActive: true,
});
assert.equal(created.name, 'Vùng kiểm thử');
assert.deepEqual(created.targetLabels, ['Người', 'Container']);
assert.equal(created.polygonPoints.length, 3);

expectValidationError(() => parseCreateZoneInput({
  cameraId: 'GATE-01',
  name: 'Không hợp lệ',
  polygonPoints: polygon,
}));
expectValidationError(() => parsePolygonPoints([{ x: 0, y: 0 }, { x: 1, y: 0 }]));
expectValidationError(() => parsePolygonPoints([{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1.1, y: 1 }]));
expectValidationError(() => parseUpdateZoneInput({}));

const update = parseUpdateZoneInput({ isActive: false, ruleType: 'PROHIBIT_SPECIFIED' });
assert.equal(update.isActive, false);
assert.equal(update.ruleType, 'PROHIBIT_SPECIFIED');

console.log('Zone validation checks passed');
