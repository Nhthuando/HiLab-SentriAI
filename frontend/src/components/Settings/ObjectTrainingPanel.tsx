import React, { useMemo, useState } from 'react';
import type { MockTrainingStatus } from '../../types';
import { CUSTOM_TRAINING_PROFILE, createTrainingJob, exportTrainingDataset, getTrainingReadiness, listTrainingJobs, returnToBaseModel, startTrainingJob, useModelVersion as activateModelVersion } from '../../api/training';
import type { TrainingReadinessResponse } from '../../api/training';

interface ObjectTrainingPanelProps { refreshKey: number; }

const buttonBase: React.CSSProperties = { border: 'none', borderRadius: '8px', padding: '7px 11px', fontSize: '11.5px', fontWeight: 700, cursor: 'pointer' };
const COCO_CLASSES = new Set(['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck']);

const StatusPill: React.FC<{ status: MockTrainingStatus }> = ({ status }) => {
  const copy: Record<MockTrainingStatus, { label: string; color: string; bg: string }> = {
    idle: { label: 'CHƯA ĐỦ MẪU', color: 'var(--ink2)', bg: 'var(--raise)' },
    queued: { label: 'ĐANG CHUẨN BỊ', color: 'var(--acc)', bg: 'var(--accq)' },
    running: { label: 'ĐANG CẢI THIỆN', color: 'var(--acc)', bg: 'var(--accq)' },
    paused_gpu: { label: 'ƯU TIÊN CAMERA', color: 'var(--p1)', bg: 'var(--p1q)' },
    evaluating: { label: 'ĐANG KIỂM TRA', color: 'var(--purple)', bg: 'var(--purpleq)' },
    candidate: { label: 'BẢN MỚI SẴN SÀNG', color: 'var(--ok)', bg: 'var(--okq)' },
    active: { label: 'ĐANG DÙNG BẢN MỚI', color: 'var(--ok)', bg: 'var(--okq)' },
    failed: { label: 'CẦN THỬ LẠI', color: 'var(--p0)', bg: 'var(--p0q)' },
  };
  const item = copy[status];
  return <span style={{ color: item.color, backgroundColor: item.bg, borderRadius: '999px', padding: '3px 8px', fontSize: '9.5px', fontWeight: 800, letterSpacing: '0.03em', whiteSpace: 'nowrap' }}>{item.label}</span>;
};

export const ObjectTrainingPanel: React.FC<ObjectTrainingPanelProps> = ({ refreshKey }) => {
  const [status, setStatus] = useState<MockTrainingStatus>('idle');
  const [activateConfirmOpen, setActivateConfirmOpen] = useState(false);
  const [rollbackConfirmOpen, setRollbackConfirmOpen] = useState(false);
  const [remoteReadiness, setRemoteReadiness] = useState<TrainingReadinessResponse | null>(null);
  const [readinessState, setReadinessState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const [candidateId, setCandidateId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  React.useEffect(() => {
    let active = true;
    const refresh = () => getTrainingReadiness().then((result) => {
      if (!active) return;
      if (result.profile !== CUSTOM_TRAINING_PROFILE) {
        throw new Error(`Máy chủ trả về profile không hợp lệ: ${result.profile || 'trống'}`);
      }
      setRemoteReadiness(result);
      setReadinessState('ready');
      setReadinessError(null);
    }).catch((error) => {
      if (!active) return;
      setRemoteReadiness(null);
      setReadinessState('error');
      setReadinessError(error instanceof Error ? error.message : 'Không thể tải điều kiện dữ liệu train từ máy chủ.');
    });
    refresh();
    const timer = window.setInterval(refresh, 8_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [refreshKey]);

  React.useEffect(() => {
    let active = true;
    const refresh = () => listTrainingJobs().then((jobs) => {
      if (!active || jobs.length === 0) return;
      const job = jobs[0];
      const nextStatus: Record<string, MockTrainingStatus> = { QUEUED: 'queued', RUNNING: 'running', PAUSED_GPU: 'paused_gpu', EVALUATING: 'evaluating', FAILED: 'failed' };
      if (job.modelVersion?.status === 'ACTIVE') { setCandidateId(job.modelVersion.id); setStatus('active'); return; }
      if (job.modelVersion?.status === 'CANDIDATE') { setCandidateId(job.modelVersion.id); setStatus('candidate'); return; }
      if (job.modelVersion?.status === 'REJECTED') { setActionError('Bản nhận diện mới chưa đạt ngưỡng chất lượng nên chưa được dùng.'); setStatus('failed'); return; }
      if (nextStatus[job.status]) setStatus(nextStatus[job.status]);
      if (job.status === 'FAILED') setActionError(job.failureReason || 'Không thể hoàn tất lần cải thiện này.');
    }).catch(() => undefined);
    refresh();
    const timer = window.setInterval(refresh, 3_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const customCoverage = useMemo(
    () => (remoteReadiness?.labelCoverage || []).filter((item) => !COCO_CLASSES.has(item.baseClass)),
    [remoteReadiness],
  );
  const progress = status === 'running' || status === 'paused_gpu' ? 54 : status === 'evaluating' || status === 'candidate' || status === 'active' ? 100 : status === 'queued' ? 8 : 0;
  const canStart = readinessState === 'ready' && remoteReadiness?.ready === true
    && (status === 'idle' || status === 'failed');
  const isProcessing = ['queued', 'running', 'paused_gpu', 'evaluating'].includes(status);

  const startTraining = async () => {
    if (!canStart) return;
    setActionError(null);
    setStatus('queued');
    try {
      const exported = await exportTrainingDataset();
      if (!exported.exported || !exported.dataset?.id) throw new Error(exported.reason || 'Không thể chuẩn bị dữ liệu train');
      const job = await createTrainingJob(exported.dataset.id);
      await startTrainingJob(job.id);
    } catch (error) {
      setStatus('failed');
      setActionError(error instanceof Error ? error.message : 'Không thể bắt đầu cải thiện nhận diện.');
    }
  };

  return (
    <section className="glass-panel" aria-label="Cải thiện nhận diện" style={{ borderRadius: '16px', padding: '15px', border: '1px solid var(--line)', boxShadow: 'var(--shadow-md)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '10px', marginBottom: '12px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexWrap: 'wrap' }}><h3 style={{ margin: 0, fontSize: '14px', color: 'var(--ink)' }}>Cải thiện nhận diện</h3><StatusPill status={status} /></div>
          <p style={{ margin: '4px 0 0', fontSize: '11px', color: 'var(--ink3)', lineHeight: 1.45 }}>1. Lưu mẫu → 2. Cải thiện nhận diện → 3. Dùng bản mới khi kết quả đạt.</p>
        </div>
        <span style={{ fontSize: '10px', color: 'var(--ink3)', paddingTop: '3px' }}>Camera luôn được ưu tiên</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(116px, 1fr))', gap: '8px', marginBottom: '12px' }}>
        {[['Mẫu đã lưu', remoteReadiness?.savedSamples ?? '—'], ['Loại đã gán', remoteReadiness?.labelsWithSamples ?? '—'], ['Ảnh / video', remoteReadiness?.sourceCount ?? '—']].map(([label, value]) => <div key={String(label)} style={{ background: 'var(--raise)', border: '1px solid var(--line)', borderRadius: '10px', padding: '9px 10px' }}><div style={{ color: 'var(--ink3)', fontSize: '10px' }}>{label}</div><div style={{ color: 'var(--ink)', fontFamily: 'var(--font-mono)', fontWeight: 800, fontSize: '17px', marginTop: '2px' }}>{value}</div></div>)}
      </div>

      {readinessState === 'loading' && <div role="status" style={{ background: 'var(--raise)', border: '1px solid var(--line)', color: 'var(--ink2)', borderRadius: '10px', padding: '9px 10px', fontSize: '11px', lineHeight: 1.45, marginBottom: '10px' }}>Đang tải điều kiện dữ liệu train từ máy chủ…</div>}
      {readinessState === 'error' && <div role="alert" style={{ background: 'var(--p0q)', border: '1px solid var(--p0)', color: 'var(--p0)', borderRadius: '10px', padding: '9px 10px', fontSize: '11px', lineHeight: 1.45, marginBottom: '10px' }}>Không thể xác minh profile {CUSTOM_TRAINING_PROFILE}. Chức năng train được khóa an toàn. {readinessError}</div>}
      {readinessState === 'ready' && !remoteReadiness?.ready && !isProcessing && <div style={{ background: 'var(--p1q)', border: '1px solid var(--p1)', color: 'var(--p1)', borderRadius: '10px', padding: '9px 10px', fontSize: '11px', lineHeight: 1.45, marginBottom: '10px' }}>Hãy lưu thêm mẫu từ nhiều ảnh hoặc video độc lập. Nút cải thiện nhận diện chỉ mở khi từng class custom đạt số mẫu, số nguồn và split được máy chủ liệt kê bên dưới.</div>}

      {isProcessing && <div aria-live="polite" style={{ background: 'var(--raise)', border: '1px solid var(--line)', borderRadius: '10px', padding: '10px', marginBottom: '10px' }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', fontSize: '10.5px', color: 'var(--ink2)', fontFamily: 'var(--font-mono)' }}><span>Tiến độ xử lý</span><span>Camera: ổn định</span></div><div style={{ height: '6px', background: 'var(--bg)', borderRadius: '999px', overflow: 'hidden', marginTop: '8px' }}><div style={{ height: '100%', width: `${progress}%`, borderRadius: 'inherit', background: status === 'paused_gpu' ? 'var(--p1)' : 'var(--acc)', transition: 'width 180ms ease' }} /></div>{status === 'paused_gpu' && <p style={{ margin: '8px 0 0', color: 'var(--p1)', fontSize: '11px', lineHeight: 1.45 }}>Camera đang hoạt động nên hệ thống tạm chờ, không tranh GPU. Khi camera rảnh, job sẽ tự tiếp tục.</p>}</div>}

      {customCoverage.length ? <div style={{ background: 'var(--raise)', border: '1px solid var(--line)', borderRadius: '10px', padding: '9px 10px', fontSize: '10.5px', lineHeight: 1.45, marginBottom: '10px' }}>
        <strong style={{ color: 'var(--ink)' }}>Bộ train custom bãi kiểm</strong>
        {customCoverage.map((item) => <div key={`${item.baseClass}:${item.label}`} style={{ color: item.ready ? 'var(--ok)' : 'var(--ink2)', marginTop: '4px', fontFamily: 'var(--font-mono)' }}>{item.label} ({item.baseClass}): {item.savedSamples}/{item.minimumSamples} ô, {item.sourceCount}/{item.minimumSources} nguồn, train/val/test {item.splitCounts.train}/{item.splitCounts.val}/{item.splitCounts.test}</div>)}
        <div style={{ color: 'var(--ink3)', marginTop: '6px' }}>Chỉ các class ngoài COCO trong profile này được đưa vào model custom. Người, xe con, xe máy, xe đạp, xe buýt và xe tải tiếp tục do model COCO nhận diện.</div>
      </div> : null}

      {actionError && <div role="alert" style={{ background: 'var(--p0q)', border: '1px solid var(--p0)', color: 'var(--p0)', borderRadius: '10px', padding: '9px 10px', fontSize: '11px', lineHeight: 1.45, marginBottom: '10px' }}>{actionError}</div>}

      {(status === 'candidate' || status === 'active') && <div aria-live="polite" style={{ border: '1px solid var(--ok)', background: 'var(--okq)', borderRadius: '10px', padding: '10px', marginBottom: '10px' }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}><strong style={{ fontSize: '11.5px', color: 'var(--ok)' }}>Bản nhận diện mới</strong><span style={{ color: 'var(--ink3)', fontSize: '10px' }}>Đã kiểm tra trước khi dùng</span></div><p style={{ margin: '7px 0 0', fontSize: '11px', color: 'var(--ink2)', lineHeight: 1.45 }}>Bản mới chỉ bổ sung các class custom có trong manifest. Các class COCO vẫn do model nền nhận diện; container tĩnh không được coi là phương tiện và chỉ detect được nếu một model ACTIVE khai báo shipping_container.</p></div>}

      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        {(status === 'idle' || status === 'failed') && <button type="button" onClick={startTraining} disabled={!canStart} aria-disabled={!canStart} style={{ ...buttonBase, color: canStart ? '#fff' : 'var(--ink3)', background: canStart ? 'var(--acc)' : 'var(--raise)', cursor: canStart ? 'pointer' : 'not-allowed' }}>{status === 'failed' ? 'Thử lại cải thiện nhận diện' : 'Bắt đầu cải thiện nhận diện'}</button>}
        {status === 'candidate' && <button type="button" onClick={() => setActivateConfirmOpen(true)} style={{ ...buttonBase, color: '#fff', background: 'var(--ok)' }}>Dùng bản nhận diện mới</button>}
        {status === 'active' && <button type="button" onClick={() => setRollbackConfirmOpen(true)} style={{ ...buttonBase, color: 'var(--p1)', background: 'transparent', border: '1px solid var(--p1)' }}>Quay về bản đang dùng trước đó</button>}
      </div>

      {activateConfirmOpen && <div role="dialog" aria-modal="true" aria-label="Xác nhận dùng bản nhận diện mới" style={{ marginTop: '10px', border: '1px solid var(--ok)', borderRadius: '10px', padding: '10px', background: 'var(--panel)' }}><p style={{ margin: '0 0 9px', fontSize: '11px', color: 'var(--ink2)', lineHeight: 1.45 }}>Dùng bản nhận diện mới? Bản đang dùng vẫn được giữ lại để có thể quay về khi cần.</p><div style={{ display: 'flex', gap: '7px' }}><button type="button" onClick={async () => { if (!candidateId) return; try { await activateModelVersion(candidateId); setStatus('active'); setActivateConfirmOpen(false); } catch (error) { setActionError(error instanceof Error ? error.message : 'Không thể dùng bản mới.'); setActivateConfirmOpen(false); } }} style={{ ...buttonBase, color: '#fff', background: 'var(--ok)' }}>Dùng bản mới</button><button type="button" onClick={() => setActivateConfirmOpen(false)} style={{ ...buttonBase, color: 'var(--ink2)', background: 'var(--raise)' }}>Hủy</button></div></div>}

      {rollbackConfirmOpen && <div role="dialog" aria-modal="true" aria-label="Xác nhận quay về bản trước" style={{ marginTop: '10px', border: '1px solid var(--p1)', borderRadius: '10px', padding: '10px', background: 'var(--panel)' }}><p style={{ margin: '0 0 9px', fontSize: '11px', color: 'var(--ink2)', lineHeight: 1.45 }}>Quay về base YOLO? Bản mới vẫn được giữ lại để có thể dùng lại sau này.</p><div style={{ display: 'flex', gap: '7px' }}><button type="button" onClick={async () => { try { await returnToBaseModel(); setStatus('candidate'); setRollbackConfirmOpen(false); } catch (error) { setActionError(error instanceof Error ? error.message : 'Không thể quay về bản nền.'); setRollbackConfirmOpen(false); } }} style={{ ...buttonBase, color: '#fff', background: 'var(--p1)' }}>Quay về bản trước</button><button type="button" onClick={() => setRollbackConfirmOpen(false)} style={{ ...buttonBase, color: 'var(--ink2)', background: 'var(--raise)' }}>Hủy</button></div></div>}
    </section>
  );
};
