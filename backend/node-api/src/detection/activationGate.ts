export interface ActivationGateResult {
  passed: boolean;
  reasonCode: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Fail closed before an evaluated model can replace the live detector. */
export function evaluateModelActivation(metrics: unknown): ActivationGateResult {
  if (!isRecord(metrics)) return { passed: false, reasonCode: 'INVALID_EVALUATION_METRICS' };
  const runtimeMode = metrics.runtimeMode ?? 'SUPPLEMENTAL';
  if (runtimeMode !== 'SUPPLEMENTAL' && runtimeMode !== 'UNIFIED') {
    return { passed: false, reasonCode: 'INVALID_RUNTIME_MODE' };
  }
  if (!isRecord(metrics.qualityGate) || metrics.qualityGate.passed !== true) {
    return { passed: false, reasonCode: 'QUALITY_GATE_NOT_PASSED' };
  }
  if (!isRecord(metrics.baseRegression) || metrics.baseRegression.passed !== true) {
    return { passed: false, reasonCode: 'BASE_REGRESSION_NOT_PASSED' };
  }
  if (runtimeMode === 'UNIFIED'
    && (!isRecord(metrics.activationGate) || metrics.activationGate.passed !== true)) {
    return { passed: false, reasonCode: 'UNIFIED_ACTIVATION_GATE_NOT_PASSED' };
  }
  return { passed: true, reasonCode: null };
}
