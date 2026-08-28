import React, { useState } from 'react';
import type { MockTrainingStatus } from '../../types';
import {
  CUSTOM_TRAINING_PROFILE,
  createTrainingJob,
  exportTrainingDataset,
  getTrainingReadiness,
  listTrainingJobs,
  returnToBaseModel,
  startTrainingJob,
  useModelVersion as activateModelVersion,
} from '../../api/training';
import type { TrainingReadinessResponse } from '../../api/training';

interface ObjectTrainingPanelProps {
  refreshKey: number;
}

const StatusPill: React.FC<{ status: MockTrainingStatus }> = ({ status }) => {
  const copy: Record<MockTrainingStatus, { label: string; color: string; bg: string; border: string }> = {
    idle: { label: 'CHƯA ĐỦ MẪU TRAIN', color: 'var(--ink2)', bg: 'var(--raise)', border: 'var(--line2)' },
    queued: { label: 'ĐANG CHUẨN BỊ', color: 'var(--acc)', bg: 'var(--accq)', border: 'var(--acc)' },
    running: { label: 'ĐANG HUẤN LUYỆN', color: 'var(--acc)', bg: 'var(--accq)', border: 'var(--acc)' },
    paused_gpu: { label: 'TẠM CHỜ GPU', color: 'var(--p1)', bg: 'var(--p1q)', border: 'var(--p1)' },
    evaluating: { label: 'ĐANG KIỂM THỬ', color: 'var(--purple)', bg: 'var(--purpleq)', border: 'var(--purple)' },
    candidate: { label: 'BẢN MỚI SẴN SÀNG', color: 'var(--ok)', bg: 'var(--okq)', border: 'var(--ok)' },
    active: { label: 'ĐANG DÙNG BẢN MỚI', color: 'var(--ok)', bg: 'var(--okq)', border: 'var(--ok)' },
    failed: { label: 'CẦN THỬ LẠI', color: 'var(--p0)', bg: 'var(--p0q)', border: 'var(--p0)' },
  };
  const item = copy[status];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        color: item.color,
        backgroundColor: item.bg,
        border: `1px solid ${item.border}`,
        borderRadius: '999px',
        padding: '3px 9px',
        fontSize: '10px',
        fontWeight: 700,
        letterSpacing: '0.02em',
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: item.color }} />
      {item.label}
    </span>
  );
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
    const refresh = () =>
      getTrainingReadiness()
        .then((result) => {
          if (!active) return;
          if (result.profile !== CUSTOM_TRAINING_PROFILE) {
            throw new Error(`Máy chủ trả về profile không hợp lệ: ${result.profile || 'trống'}`);
          }
          setRemoteReadiness(result);
          setReadinessState('ready');
          setReadinessError(null);
        })
        .catch((error) => {
          if (!active) return;
          setRemoteReadiness(null);
          setReadinessState('error');
          setReadinessError(error instanceof Error ? error.message : 'Không thể tải điều kiện dữ liệu train từ máy chủ.');
        });
    refresh();
    const timer = window.setInterval(refresh, 8_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshKey]);

  React.useEffect(() => {
    let active = true;
    const refresh = () =>
      listTrainingJobs()
        .then((jobs) => {
          if (!active || jobs.length === 0) return;
          const job = jobs[0];
          const nextStatus: Record<string, MockTrainingStatus> = {
            QUEUED: 'queued',
            RUNNING: 'running',
            PAUSED_GPU: 'paused_gpu',
            EVALUATING: 'evaluating',
            FAILED: 'failed',
          };
          if (job.modelVersion?.status === 'ACTIVE') {
            setCandidateId(job.modelVersion.id);
            setStatus('active');
            return;
          }
          if (job.modelVersion?.status === 'CANDIDATE') {
            setCandidateId(job.modelVersion.id);
            setStatus('candidate');
            return;
          }
          if (job.modelVersion?.status === 'REJECTED') {
            setActionError('Bản nhận diện mới chưa đạt ngưỡng chất lượng nên chưa được dùng.');
            setStatus('failed');
            return;
          }
          if (nextStatus[job.status]) setStatus(nextStatus[job.status]);
          if (job.status === 'FAILED') setActionError(job.failureReason || 'Không thể hoàn tất lần cải thiện này.');
        })
        .catch(() => undefined);
    refresh();
    const timer = window.setInterval(refresh, 3_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const progress =
    status === 'running' || status === 'paused_gpu'
      ? 54
      : status === 'evaluating' || status === 'candidate' || status === 'active'
        ? 100
        : status === 'queued'
          ? 8
          : 0;
  const canStart =
    readinessState === 'ready' && remoteReadiness?.ready === true && (status === 'idle' || status === 'failed');
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
    <section
      className="glass-panel"
      aria-label="Cải thiện nhận diện"
      style={{
        borderRadius: '16px',
        padding: '18px 20px',
        border: '1px solid var(--line2)',
        boxShadow: 'var(--shadow-md)',
        backgroundColor: 'var(--panel)',
      }}
    >
      {/* Header Section */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '12px',
          marginBottom: '14px',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>⚡</span> Cải thiện nhận diện AI
            </h3>
            <StatusPill status={status} />
          </div>
          <p style={{ margin: '5px 0 0', fontSize: '11.5px', color: 'var(--ink2)', lineHeight: 1.45 }}>
            Quy trình: <b>1. Lưu mẫu</b> → <b>2. Huấn luyện</b> → <b>3. Áp dụng bản mới khi đạt</b>
          </p>
        </div>
        <span
          style={{
            fontSize: '10.5px',
            color: 'var(--ok)',
            backgroundColor: 'var(--okq)',
            border: '1px solid var(--ok)',
            padding: '3px 8px',
            borderRadius: '6px',
            fontWeight: 600,
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          <span>🛡️</span> Camera luôn được ưu tiên
        </span>
      </div>

      {/* Metrics Row (3 Cards) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: '10px',
          marginBottom: '14px',
        }}
      >
        {[
          { label: 'Mẫu đã lưu', value: remoteReadiness?.savedSamples ?? '0', icon: '🏷️' },
          { label: 'Loại đã gán', value: remoteReadiness?.labelsWithSamples ?? '0', icon: '📦' },
          { label: 'Ảnh / video', value: remoteReadiness?.sourceCount ?? '0', icon: '🎬' },
        ].map((item) => (
          <div
            key={item.label}
            style={{
              background: 'var(--card)',
              border: '1px solid var(--line)',
              borderRadius: '12px',
              padding: '10px 12px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ color: 'var(--ink3)', fontSize: '11px', fontWeight: 500, display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span>{item.icon}</span> {item.label}
            </div>
            <div style={{ color: 'var(--ink)', fontFamily: 'var(--font-mono)', fontWeight: 800, fontSize: '19px', marginTop: '4px' }}>
              {item.value}
            </div>
          </div>
        ))}
      </div>

      {/* States Feedback */}
      {readinessState === 'loading' && (
        <div
          role="status"
          style={{
            background: 'var(--raise)',
            border: '1px solid var(--line)',
            color: 'var(--ink2)',
            borderRadius: '10px',
            padding: '10px 14px',
            fontSize: '11.5px',
            lineHeight: 1.45,
            marginBottom: '12px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span>⏳</span> Đang tải điều kiện dữ liệu huấn luyện từ máy chủ…
        </div>
      )}

      {readinessState === 'error' && (
        <div
          role="alert"
          style={{
            background: 'var(--p0q)',
            border: '1px solid var(--p0)',
            color: 'var(--p0)',
            borderRadius: '10px',
            padding: '10px 14px',
            fontSize: '11.5px',
            lineHeight: 1.45,
            marginBottom: '12px',
          }}
        >
          <b>Lỗi kiểm tra profile:</b> Không thể xác minh {CUSTOM_TRAINING_PROFILE}. Chức năng train được khóa an toàn. {readinessError}
        </div>
      )}

      {readinessState === 'ready' && !remoteReadiness?.ready && !isProcessing && (
        <div
          style={{
            background: 'var(--p1q)',
            border: '1px solid var(--p1)',
            color: 'var(--ink)',
            borderRadius: '10px',
            padding: '10px 14px',
            fontSize: '11.5px',
            lineHeight: 1.5,
            marginBottom: '12px',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--p1)', marginBottom: '3px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span>⚠️</span> Yêu cầu dữ liệu để huấn luyện:
          </div>
          <div style={{ color: 'var(--ink2)', fontSize: '11px' }}>
            Hãy lưu thêm mẫu từ các tệp ảnh hoặc video. Nút <b>"Bắt đầu cải thiện nhận diện"</b> sẽ tự động mở khóa khi có đủ dữ liệu mẫu hợp lệ.
          </div>
        </div>
      )}

      {/* Training In Progress Bar */}
      {isProcessing && (
        <div
          aria-live="polite"
          style={{
            background: 'var(--card)',
            border: '1px solid var(--line2)',
            borderRadius: '12px',
            padding: '12px 14px',
            marginBottom: '12px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', fontSize: '11.5px', color: 'var(--ink2)', fontWeight: 600 }}>
            <span>⚡ Tiến độ xử lý trên máy chủ</span>
            <span style={{ color: 'var(--ok)', fontFamily: 'var(--font-mono)' }}>Camera: Ổn định</span>
          </div>
          <div style={{ height: '8px', background: 'var(--raise)', borderRadius: '999px', overflow: 'hidden', marginTop: '10px' }}>
            <div
              style={{
                height: '100%',
                width: `${progress}%`,
                borderRadius: 'inherit',
                background: status === 'paused_gpu' ? 'var(--p1)' : 'var(--acc)',
                transition: 'width 240ms ease',
              }}
            />
          </div>
          {status === 'paused_gpu' && (
            <p style={{ margin: '8px 0 0', color: 'var(--p1)', fontSize: '11px', lineHeight: 1.45 }}>
              Camera giám sát đang hoạt động tải cao nên GPU được ưu tiên cho camera. Khi camera rảnh, tiến trình sẽ tự động tiếp tục.
            </p>
          )}
        </div>
      )}

      {actionError && (
        <div
          role="alert"
          style={{
            background: 'var(--p0q)',
            border: '1px solid var(--p0)',
            color: 'var(--p0)',
            borderRadius: '10px',
            padding: '10px 14px',
            fontSize: '11.5px',
            lineHeight: 1.45,
            marginBottom: '12px',
          }}
        >
          {actionError}
        </div>
      )}

      {/* Active Model Status Box */}
      {(status === 'candidate' || status === 'active') && (
        <div
          aria-live="polite"
          style={{
            border: '1px solid var(--ok)',
            background: 'var(--okq)',
            borderRadius: '12px',
            padding: '12px 14px',
            marginBottom: '14px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
            <strong style={{ fontSize: '12.5px', color: 'var(--ok)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>✓</span> Bản nhận diện mới đang hoạt động
            </strong>
            <span style={{ color: 'var(--ok)', fontSize: '10.5px', fontWeight: 600 }}>Đã kiểm tra an toàn</span>
          </div>
          <p style={{ margin: '6px 0 0', fontSize: '11px', color: 'var(--ink2)', lineHeight: 1.45 }}>
            Bản mới đã được áp dụng tự động cho camera. Các đối tượng cơ bản vẫn được giữ nguyên để đảm bảo độ tin cậy.
          </p>
        </div>
      )}

      {/* Action Buttons */}
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
        {(status === 'idle' || status === 'failed') && (
          <button
            type="button"
            onClick={startTraining}
            disabled={!canStart}
            aria-disabled={!canStart}
            style={{
              padding: '10px 18px',
              borderRadius: '10px',
              border: 'none',
              fontSize: '12.5px',
              fontWeight: 700,
              cursor: canStart ? 'pointer' : 'not-allowed',
              color: canStart ? '#ffffff' : 'var(--ink3)',
              backgroundColor: canStart ? 'var(--acc)' : 'var(--raise)',
              boxShadow: canStart ? '0 2px 10px var(--acc-glow)' : 'none',
              transition: 'all 0.16s ease',
            }}
          >
            {status === 'failed' ? '🔄 Thử lại cải thiện nhận diện' : '🚀 Bắt đầu cải thiện nhận diện'}
          </button>
        )}

        {status === 'candidate' && (
          <button
            type="button"
            onClick={() => setActivateConfirmOpen(true)}
            style={{
              padding: '10px 18px',
              borderRadius: '10px',
              border: 'none',
              fontSize: '12.5px',
              fontWeight: 700,
              cursor: 'pointer',
              color: '#ffffff',
              backgroundColor: 'var(--ok)',
              boxShadow: '0 2px 10px var(--ok-glow)',
            }}
          >
            ✓ Dùng bản nhận diện mới
          </button>
        )}

        {status === 'active' && (
          <button
            type="button"
            onClick={() => setRollbackConfirmOpen(true)}
            style={{
              padding: '9px 16px',
              borderRadius: '10px',
              border: '1px solid var(--p1)',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
              color: 'var(--p1)',
              backgroundColor: 'transparent',
              transition: 'all 0.16s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--p1q)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            ↩ Quay về bản đang dùng trước đó
          </button>
        )}
      </div>

      {/* Confirmation Dialogs */}
      {activateConfirmOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Xác nhận dùng bản nhận diện mới"
          style={{
            marginTop: '12px',
            border: '1px solid var(--ok)',
            borderRadius: '12px',
            padding: '12px 14px',
            background: 'var(--card)',
          }}
        >
          <p style={{ margin: '0 0 10px', fontSize: '11.5px', color: 'var(--ink)', lineHeight: 1.45 }}>
            <b>Xác nhận kích hoạt:</b> Áp dụng phiên bản nhận diện AI mới vào camera? Bản đang dùng vẫn được sao lưu an toàn để có thể quay về bất cứ lúc nào.
          </p>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              onClick={async () => {
                if (!candidateId) return;
                try {
                  await activateModelVersion(candidateId);
                  setStatus('active');
                  setActivateConfirmOpen(false);
                } catch (error) {
                  setActionError(error instanceof Error ? error.message : 'Không thể dùng bản mới.');
                  setActivateConfirmOpen(false);
                }
              }}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: 'none',
                color: '#fff',
                background: 'var(--ok)',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              Xác nhận dùng
            </button>
            <button
              type="button"
              onClick={() => setActivateConfirmOpen(false)}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: '1px solid var(--line2)',
                color: 'var(--ink2)',
                background: 'var(--raise)',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Hủy
            </button>
          </div>
        </div>
      )}

      {rollbackConfirmOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Xác nhận quay về bản trước"
          style={{
            marginTop: '12px',
            border: '1px solid var(--p1)',
            borderRadius: '12px',
            padding: '12px 14px',
            background: 'var(--card)',
          }}
        >
          <p style={{ margin: '0 0 10px', fontSize: '11.5px', color: 'var(--ink)', lineHeight: 1.45 }}>
            <b>Xác nhận hoàn tác:</b> Bạn có muốn quay về mô hình trước đó? Bản mới vẫn được lưu trữ để có thể tái sử dụng bất cứ lúc nào.
          </p>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              onClick={async () => {
                try {
                  await returnToBaseModel();
                  setStatus('candidate');
                  setRollbackConfirmOpen(false);
                } catch (error) {
                  setActionError(error instanceof Error ? error.message : 'Không thể quay về bản nền.');
                  setRollbackConfirmOpen(false);
                }
              }}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: 'none',
                color: '#fff',
                background: 'var(--p1)',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              Xác nhận quay về
            </button>
            <button
              type="button"
              onClick={() => setRollbackConfirmOpen(false)}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: '1px solid var(--line2)',
                color: 'var(--ink2)',
                background: 'var(--raise)',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Hủy
            </button>
          </div>
        </div>
      )}
    </section>
  );
};

