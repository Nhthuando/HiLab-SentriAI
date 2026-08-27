import assert from 'node:assert/strict';
import { evaluateModelActivation } from '../detection/activationGate';

assert.equal(evaluateModelActivation({
  qualityGate: { passed: true },
  baseRegression: { passed: true },
}).passed, true);

assert.deepEqual(evaluateModelActivation({
  runtimeMode: 'UNIFIED',
  qualityGate: { passed: true },
  baseRegression: { passed: true },
  activationGate: { passed: false },
}), {
  passed: false,
  reasonCode: 'UNIFIED_ACTIVATION_GATE_NOT_PASSED',
});

assert.equal(evaluateModelActivation({
  runtimeMode: 'UNIFIED',
  qualityGate: { passed: true },
  baseRegression: { passed: true },
  activationGate: { passed: true },
}).passed, true);

assert.equal(evaluateModelActivation({
  runtimeMode: 'UNIFIED',
  qualityGate: { passed: true },
  baseRegression: { passed: false },
  activationGate: { passed: true },
}).reasonCode, 'BASE_REGRESSION_NOT_PASSED');

console.log('model activation gate: PASS');
