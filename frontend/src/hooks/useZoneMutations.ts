import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type {
  PolygonZone,
  ZoneMutationNotice,
  ZoneMutationStatus,
} from '../types';
import {
  createZone as createZoneRequest,
  deleteZone as deleteZoneRequest,
  updateZone as updateZoneRequest,
  zonePatchToWrite,
  zoneRecordToView,
  zoneViewToWrite,
} from '../api/zones';

interface ZoneMutationEntry {
  camId: string;
  zoneId: string;
  revision: number;
  queuedPatch?: Partial<PolygonZone>;
  queuedRollback?: PolygonZone;
  timer?: number;
  inFlight?: Promise<void>;
  deleteStarted?: boolean;
  deleting?: boolean;
  temp?: boolean;
  deletedBeforeCreate?: boolean;
  createPromise?: Promise<PolygonZone>;
  deleteRollback?: PolygonZone;
}

interface UseZoneMutationsOptions {
  zonesByCam: Record<string, PolygonZone[]>;
  setZonesByCam: Dispatch<SetStateAction<Record<string, PolygonZone[]>>>;
  allLabelNames: string[];
  detectableLabelNames: string[];
  registryReady: boolean;
  setEditorError: Dispatch<SetStateAction<string | null>>;
}

const UPDATE_DEBOUNCE_MS = 100;

function entryKey(camId: string, zoneId: string): string {
  return `${camId}\u0000${zoneId}`;
}

export function useZoneMutations({
  zonesByCam,
  setZonesByCam,
  allLabelNames,
  detectableLabelNames,
  registryReady,
  setEditorError,
}: UseZoneMutationsOptions) {
  const zonesRef = useRef(zonesByCam);
  const allLabelNamesRef = useRef(allLabelNames);
  const detectableLabelNamesRef = useRef(detectableLabelNames);
  const entriesRef = useRef(new Map<string, ZoneMutationEntry>());
  const mountedRef = useRef(true);
  const noticeSequenceRef = useRef(0);
  const [statusByZoneId, setStatusByZoneId] = useState<Record<string, ZoneMutationStatus>>({});
  const [notice, setNotice] = useState<ZoneMutationNotice | null>(null);

  useEffect(() => {
    zonesRef.current = zonesByCam;
  }, [zonesByCam]);

  useEffect(() => {
    allLabelNamesRef.current = allLabelNames;
  }, [allLabelNames]);

  useEffect(() => {
    detectableLabelNamesRef.current = detectableLabelNames;
  }, [detectableLabelNames]);

  useEffect(() => {
    mountedRef.current = true;
    const entries = entriesRef.current;
    return () => {
      mountedRef.current = false;
      for (const entry of entries.values()) {
        if (entry.timer !== undefined) window.clearTimeout(entry.timer);
      }
    };
  }, []);

  const applyZones = useCallback((
    camId: string,
    updater: (zones: PolygonZone[]) => PolygonZone[],
  ) => {
    const current = zonesRef.current;
    const next = {
      ...current,
      [camId]: updater(current[camId] || []),
    };
    zonesRef.current = next;
    setZonesByCam(next);
  }, [setZonesByCam]);

  const publishNotice = useCallback((kind: 'success' | 'error', message: string) => {
    if (!mountedRef.current) return;
    noticeSequenceRef.current += 1;
    setNotice({ id: noticeSequenceRef.current, kind, message });
  }, []);

  const updateStatus = useCallback((zoneId: string, status?: ZoneMutationStatus) => {
    if (!mountedRef.current) return;
    setStatusByZoneId((previous) => {
      if (status) return { ...previous, [zoneId]: status };
      const { [zoneId]: _removed, ...remaining } = previous;
      return remaining;
    });
  }, []);

  const findZone = useCallback((camId: string, zoneId: string) => (
    (zonesRef.current[camId] || []).find((zone) => zone.id === zoneId)
  ), []);

  const performDeleteRef = useRef<(entry: ZoneMutationEntry) => void>(() => undefined);
  const scheduleFlushRef = useRef<(entry: ZoneMutationEntry, delay?: number) => void>(() => undefined);

  const flushEntry = useCallback((entry: ZoneMutationEntry) => {
    if (entry.temp || entry.deleting || entry.inFlight || !entry.queuedPatch) return;

    if (entry.timer !== undefined) {
      window.clearTimeout(entry.timer);
      entry.timer = undefined;
    }

    const currentZone = findZone(entry.camId, entry.zoneId);
    if (!currentZone) return;

    const batchPatch = entry.queuedPatch;
    const batchRollback = entry.queuedRollback || currentZone;
    const requestRevision = entry.revision;
    entry.queuedPatch = undefined;
    entry.queuedRollback = undefined;

    const payload = zonePatchToWrite(
      batchPatch,
      currentZone,
      detectableLabelNamesRef.current,
    );
    if (!payload) {
      updateStatus(entry.zoneId, { phase: 'saved' });
      return;
    }

    updateStatus(entry.zoneId, { phase: 'saving' });
    const request = updateZoneRequest(entry.zoneId, payload)
      .then((record) => {
        if (entry.deleting) return;
        const hasNewerChange = entry.revision !== requestRevision || Boolean(entry.queuedPatch);
        if (!hasNewerChange) {
          const persisted = zoneRecordToView(record, allLabelNamesRef.current);
          applyZones(entry.camId, (zones) => zones.map((zone) => (
            zone.id === entry.zoneId ? { ...persisted, color: zone.color } : zone
          )));
          updateStatus(entry.zoneId, { phase: 'saved' });
          setEditorError(null);
        }
      })
      .catch((error) => {
        console.error(`Failed to update zone ${entry.zoneId}:`, error);
        if (entry.deleting) return;

        const hasNewerChange = entry.revision !== requestRevision || Boolean(entry.queuedPatch);
        if (hasNewerChange) {
          entry.queuedPatch = { ...batchPatch, ...entry.queuedPatch };
          entry.queuedRollback = batchRollback;
          return;
        }

        applyZones(entry.camId, (zones) => zones.map((zone) => (
          zone.id === entry.zoneId ? batchRollback : zone
        )));
        const message = `Không thể lưu thay đổi Zone ${entry.camId}. Chỉ thay đổi vừa lỗi đã được hoàn tác.`;
        updateStatus(entry.zoneId, { phase: 'error', message });
        setEditorError(message);
        publishNotice('error', message);
      });

    entry.inFlight = request;
    void request.finally(() => {
      if (entry.inFlight === request) entry.inFlight = undefined;
      if (entry.deleting) {
        performDeleteRef.current(entry);
      } else if (entry.queuedPatch) {
        scheduleFlushRef.current(entry, 0);
      }
    });
  }, [applyZones, findZone, publishNotice, setEditorError, updateStatus]);

  const scheduleFlush = useCallback((entry: ZoneMutationEntry, delay = UPDATE_DEBOUNCE_MS) => {
    if (entry.temp || entry.deleting || entry.inFlight) return;
    if (entry.timer !== undefined) window.clearTimeout(entry.timer);
    entry.timer = window.setTimeout(() => flushEntry(entry), delay);
  }, [flushEntry]);

  scheduleFlushRef.current = scheduleFlush;

  const performDelete = useCallback((entry: ZoneMutationEntry) => {
    if (entry.deleteStarted || entry.inFlight || entry.temp || !entry.deleting) return;
    entry.deleteStarted = true;
    const deletedZoneId = entry.zoneId;
    const key = entryKey(entry.camId, deletedZoneId);

    void deleteZoneRequest(deletedZoneId)
      .then(() => {
        entriesRef.current.delete(key);
        updateStatus(deletedZoneId);
        setEditorError(null);
        publishNotice('success', 'Đã xóa Zone trên máy chủ.');
      })
      .catch((error) => {
        console.error(`Failed to delete zone ${deletedZoneId}:`, error);
        entry.deleteStarted = false;
        entry.deleting = false;
        const rollback = entry.deleteRollback;
        if (rollback && !findZone(entry.camId, rollback.id)) {
          applyZones(entry.camId, (zones) => [...zones, rollback]);
        }
        const message = 'Không thể xóa Zone. Zone vừa xóa đã được khôi phục.';
        updateStatus(deletedZoneId, { phase: 'error', message });
        setEditorError(message);
        publishNotice('error', message);
      });
  }, [applyZones, findZone, publishNotice, setEditorError, updateStatus]);

  performDeleteRef.current = performDelete;

  const updateZone = useCallback((camId: string, zoneId: string, patch: Partial<PolygonZone>) => {
    if (!registryReady) {
      setEditorError('Chưa thể lưu Zone vì danh mục nhãn chưa tải thành công.');
      return;
    }

    const currentZone = findZone(camId, zoneId);
    if (!currentZone) return;
    const key = entryKey(camId, zoneId);
    const entry = entriesRef.current.get(key) || {
      camId,
      zoneId,
      revision: 0,
    };
    if (entry.deleting) return;
    entriesRef.current.set(key, entry);

    const nextZone = { ...currentZone, ...patch };
    applyZones(camId, (zones) => zones.map((zone) => (
      zone.id === zoneId ? nextZone : zone
    )));

    const serverPatch = zonePatchToWrite(
      patch,
      nextZone,
      detectableLabelNamesRef.current,
    );
    if (!serverPatch) {
      updateStatus(zoneId, { phase: 'saved' });
      return;
    }

    entry.revision += 1;
    entry.queuedRollback ||= currentZone;
    entry.queuedPatch = { ...entry.queuedPatch, ...patch };
    updateStatus(zoneId, { phase: 'saving' });
    scheduleFlush(entry);
  }, [applyZones, findZone, registryReady, scheduleFlush, setEditorError, updateStatus]);

  const addZone = useCallback((camId: string, newZone: PolygonZone): Promise<PolygonZone> => {
    if (!registryReady) {
      const message = 'Chưa thể tạo Zone vì danh mục nhãn chưa tải thành công.';
      setEditorError(message);
      return Promise.reject(new Error(message));
    }

    const key = entryKey(camId, newZone.id);
    const entry: ZoneMutationEntry = {
      camId,
      zoneId: newZone.id,
      revision: 0,
      temp: true,
    };
    entriesRef.current.set(key, entry);
    applyZones(camId, (zones) => [...zones, newZone]);
    updateStatus(newZone.id, { phase: 'saving' });

    const request = createZoneRequest(
      zoneViewToWrite(newZone, detectableLabelNamesRef.current, camId),
    )
      .then(async (record) => {
        const persistedBase = zoneRecordToView(record, allLabelNamesRef.current);
        const latestTemp = findZone(camId, newZone.id) || newZone;
        const persisted: PolygonZone = {
          ...persistedBase,
          ...latestTemp,
          id: persistedBase.id,
          color: latestTemp.color,
        };

        entriesRef.current.delete(key);
        updateStatus(newZone.id);
        entry.temp = false;
        entry.zoneId = persisted.id;
        if (entry.queuedRollback) {
          entry.queuedRollback = { ...entry.queuedRollback, id: persisted.id };
        }

        if (entry.deletedBeforeCreate) {
          entry.deleting = true;
          entry.deleteRollback = persisted;
          entriesRef.current.set(entryKey(camId, persisted.id), entry);
          updateStatus(persisted.id, { phase: 'deleting' });
          performDeleteRef.current(entry);
          throw new Error('ZONE_CREATE_CANCELLED');
        }

        applyZones(camId, (zones) => zones.map((zone) => (
          zone.id === newZone.id ? persisted : zone
        )));
        entriesRef.current.set(entryKey(camId, persisted.id), entry);
        updateStatus(persisted.id, entry.queuedPatch ? { phase: 'saving' } : { phase: 'saved' });
        setEditorError(null);
        publishNotice('success', 'Đã tạo Zone mới trên máy chủ.');
        if (entry.queuedPatch) scheduleFlushRef.current(entry, 0);
        return persisted;
      })
      .catch((error) => {
        if (error instanceof Error && error.message === 'ZONE_CREATE_CANCELLED') throw error;
        console.error(`Failed to create zone for ${camId}:`, error);
        entriesRef.current.delete(key);
        if (!entry.deletedBeforeCreate) {
          applyZones(camId, (zones) => zones.filter((zone) => zone.id !== newZone.id));
        }
        const message = `Không thể tạo Zone ${camId}. Zone tạm đã được gỡ bỏ.`;
        updateStatus(newZone.id, { phase: 'error', message });
        setEditorError(message);
        publishNotice('error', message);
        throw error;
      });

    entry.createPromise = request;
    return request;
  }, [applyZones, findZone, publishNotice, registryReady, setEditorError, updateStatus]);

  const deleteZone = useCallback((camId: string, zoneId: string) => {
    if (!registryReady) {
      setEditorError('Chưa thể xóa Zone vì danh mục nhãn chưa tải thành công.');
      return;
    }

    const zone = findZone(camId, zoneId);
    if (!zone) return;
    const key = entryKey(camId, zoneId);
    const entry = entriesRef.current.get(key) || {
      camId,
      zoneId,
      revision: 0,
    };
    if (entry.deleting || entry.deletedBeforeCreate) return;
    entriesRef.current.set(key, entry);

    entry.revision += 1;
    entry.deleting = true;
    entry.deleteRollback = zone;
    entry.queuedPatch = undefined;
    entry.queuedRollback = undefined;
    if (entry.timer !== undefined) {
      window.clearTimeout(entry.timer);
      entry.timer = undefined;
    }

    applyZones(camId, (zones) => zones.filter((candidate) => candidate.id !== zoneId));
    updateStatus(zoneId, { phase: 'deleting' });

    if (entry.temp) {
      entry.deletedBeforeCreate = true;
      return;
    }
    if (!entry.inFlight) performDelete(entry);
  }, [applyZones, findZone, performDelete, registryReady, setEditorError, updateStatus]);

  return {
    updateZone,
    addZone,
    deleteZone,
    statusByZoneId,
    notice,
  };
}
