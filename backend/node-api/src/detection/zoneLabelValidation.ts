import {
  normalizeDisplayNameKey,
  type DetectionCapability,
} from './taxonomy';

/** A write-time policy error that the zone route can expose without parsing it. */
export class ZoneLabelValidationError extends Error {
  constructor(
    readonly reasonCode: 'LABEL_NOT_REGISTERED' | 'LABEL_NOT_DETECTABLE' | 'LABEL_AMBIGUOUS',
    readonly rejectedDisplayName: string,
    message: string,
  ) {
    super(message);
    this.name = 'ZoneLabelValidationError';
  }
}

function capabilityLookup(
  capabilitiesByName: ReadonlyMap<string, DetectionCapability>,
): ReadonlyMap<string, { displayName: string; capability: DetectionCapability }> {
  const byNormalizedName = new Map<string, { displayName: string; capability: DetectionCapability }>();
  for (const [displayName, capability] of capabilitiesByName) {
    const key = normalizeDisplayNameKey(displayName);
    const existing = byNormalizedName.get(key);
    if (existing !== undefined && existing.displayName !== displayName) {
      throw new ZoneLabelValidationError(
        'LABEL_AMBIGUOUS',
        displayName,
        `Nhãn '${displayName}' trùng tên chuẩn hoá với nhãn '${existing.displayName}' trong Danh sách Nhãn Đối Tượng`,
      );
    }
    byNormalizedName.set(key, { displayName, capability });
  }
  return byNormalizedName;
}

/**
 * Canonicalize zone target labels against the current registry capability
 * snapshot. This intentionally performs syntax-only display-name matching:
 * no semantic aliases are accepted for zone writes.
 */
export function validateDetectableTargetLabels(
  labels: readonly string[],
  capabilitiesByName: ReadonlyMap<string, DetectionCapability>,
): string[] {
  const registered = capabilityLookup(capabilitiesByName);
  const seen = new Set<string>();
  const normalizedLabels: string[] = [];

  for (const rawLabel of labels) {
    const requestedDisplayName = rawLabel.trim();
    const key = normalizeDisplayNameKey(requestedDisplayName);
    const entry = registered.get(key);
    if (entry === undefined) {
      throw new ZoneLabelValidationError(
        'LABEL_NOT_REGISTERED',
        requestedDisplayName,
        `Nhãn '${requestedDisplayName}' chưa được đăng ký trong Danh sách Nhãn Đối Tượng`,
      );
    }
    if (!entry.capability.isDetectable) {
      throw new ZoneLabelValidationError(
        'LABEL_NOT_DETECTABLE',
        entry.displayName,
        `Nhãn '${entry.displayName}' chưa có model nhận diện`,
      );
    }
    if (!seen.has(key)) {
      seen.add(key);
      normalizedLabels.push(entry.displayName);
    }
  }

  return normalizedLabels;
}
