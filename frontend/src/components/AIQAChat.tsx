import React, { useState, useRef, useEffect } from 'react';
import type { ActivityEvidence, ChatMessage } from '../types';
import { resolveMediaUrl } from '../api/client';
import { useDeferredEvidenceClip } from '../hooks/useDeferredEvidenceClip';

interface AIQAChatProps {
  messages: ChatMessage[];
  onSendMessage: (text: string) => Promise<void>;
  onClearChat?: () => Promise<void>;
  isHistoryLoading: boolean;
  isSending: boolean;
  error: string | null;
}

function renderAssistantText(text: string): React.ReactNode {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${index}-${part}`}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={`${index}-${part}`}>{part}</React.Fragment>;
  });
}

const ActivityEvidenceCard: React.FC<{ initial: ActivityEvidence }> = ({ initial }) => {
  const { evidence, request, requestError, isBusy } = useDeferredEvidenceClip(initial);
  const canRetry = evidence.canRequestClip && ['NOT_REQUESTED', 'FAILED', 'EXPIRED'].includes(evidence.clipStatus);
  const clipId = evidence.clipStatus === 'READY' ? evidence.clipId : null;

  return (
    <div className="glass-panel" style={{ marginTop: '10px', borderRadius: '14px', overflow: 'hidden', maxWidth: '480px', border: '1px solid var(--line2)' }}>
      {clipId ? (
        <div style={{ aspectRatio: '16/9', background: '#06080b' }}>
          <video
            controls
            preload="none"
            src={resolveMediaUrl(`/api/v1/clips/${encodeURIComponent(clipId)}/stream`)}
            aria-label={`Clip hoạt động: ${evidence.title}`}
            style={{ width: '100%', height: '100%', display: 'block', objectFit: 'contain' }}
          />
        </div>
      ) : (
        <div style={{ padding: '18px', background: 'linear-gradient(135deg, color-mix(in srgb, var(--ok) 9%, var(--card)), var(--card))' }}>
          <div style={{ fontSize: '12px', color: 'var(--ink2)', marginBottom: '6px' }}>{evidence.cam} · {evidence.from}–{evidence.to}</div>
          <div style={{ fontWeight: 650, color: 'var(--ink)', marginBottom: '12px' }}>{evidence.title}</div>
          {canRetry ? (
            <button
              type="button"
              onClick={() => void request()}
              disabled={isBusy}
              title="Video chỉ được tạo sau khi bấm nút này"
              style={{ border: '1px solid color-mix(in srgb, var(--ok) 55%, var(--line2))', borderRadius: '8px', padding: '7px 13px', background: 'color-mix(in srgb, var(--ok) 14%, var(--raise))', color: 'var(--ink)', cursor: 'pointer', fontWeight: 650 }}
            >
              ▶ {evidence.clipStatus === 'NOT_REQUESTED' ? 'Xem video' : 'Thử tạo lại video'}
            </button>
          ) : isBusy ? (
            <div role="status" style={{ color: 'var(--ink2)', fontSize: '12px' }}>Đang tạo video 10 giây…</div>
          ) : (
            <div style={{ color: 'var(--ink3)', fontSize: '12px' }}>{evidence.message || 'Không thể tạo video cho lượt hoạt động này.'}</div>
          )}
          {(requestError || evidence.message) && (
            <div role="alert" style={{ marginTop: '9px', color: 'var(--p0)', fontSize: '11.5px' }}>{requestError || evidence.message}</div>
          )}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 14px' }}>
        <span style={{ flex: 1, fontSize: '12px', color: 'var(--ink2)' }}>{evidence.title}</span>
        {clipId && (
          <a href={resolveMediaUrl(`/api/v1/clips/${encodeURIComponent(clipId)}/download`)} download style={{ color: 'var(--acc)', fontSize: '11.5px', fontWeight: 650, textDecoration: 'none' }}>
            Tải clip 10s
          </a>
        )}
      </div>
    </div>
  );
};

export const AIQAChat: React.FC<AIQAChatProps> = ({
  messages,
  onSendMessage,
  onClearChat,
  isHistoryLoading,
  isSending,
  error,
}) => {
  const [inputVal, setInputVal] = useState<string>('');
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const suggestedQuestions = [
    'Hôm nay có bao nhiêu xe lạ vào?',
    'Có xe máy hay xe hơi nào vào khu vực cấm không?',
    'Xe nâng hoạt động thế nào hôm nay?',
    'Xe 15R-158.45 vào mấy lần hôm nay?'
  ];

  const handleSend = () => {
    const trimmed = inputVal.trim();
    if (!trimmed || isSending || isHistoryLoading) return;
    void onSendMessage(trimmed);
    setInputVal('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard?.writeText(text);
    setCopiedMsgId(id);
    setTimeout(() => setCopiedMsgId(null), 2000);
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isSending, error]);

  return (
    <div
      style={{
        maxWidth: '880px',
        margin: '0 auto',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        height: 'calc(100vh - 66px)'
      }}
    >
      {/* Top Action Bar if user wants to clear or see message count */}
      {messages.length > 0 && onClearChat && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '8px' }}>
          <button
            onClick={() => void onClearChat()}
            disabled={isSending}
            style={{
              fontSize: '11.5px',
              fontWeight: 500,
              color: 'var(--ink3)',
              backgroundColor: 'transparent',
              border: 'none',
              cursor: isSending ? 'not-allowed' : 'pointer',
              opacity: isSending ? 0.55 : 1,
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              padding: '4px 8px',
              borderRadius: '6px'
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--ink)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--ink3)')}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
            Xóa lịch sử chat
          </button>
        </div>
      )}

      {/* Messages Scroll Area */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '18px',
          padding: '6px 4px'
        }}
      >
        {isHistoryLoading && (
          <div
            role="status"
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '10px',
              color: 'var(--ink3)',
              fontSize: '13px',
            }}
          >
            <span
              aria-hidden="true"
              style={{
                width: '16px',
                height: '16px',
                border: '2px solid var(--line2)',
                borderTopColor: 'var(--acc)',
                borderRadius: '50%',
                animation: 'qa-spin 0.8s linear infinite',
              }}
            />
            Đang tải lịch sử chat…
          </div>
        )}

        {!isHistoryLoading && messages.length === 0 && (
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              textAlign: 'center',
              padding: '28px 18px',
            }}
          >
            <span
              style={{
                width: '46px',
                height: '46px',
                borderRadius: '14px',
                background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 8px 24px rgba(59, 130, 246, 0.3)',
                marginBottom: '14px',
              }}
            >
              <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2">
                <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
              </svg>
            </span>
            <strong style={{ color: 'var(--ink)', fontSize: '15px', marginBottom: '6px' }}>
              Hỏi về dữ liệu camera đã lưu
            </strong>
            <span style={{ color: 'var(--ink3)', fontSize: '13px', maxWidth: '420px', lineHeight: 1.6 }}>
              Chọn câu hỏi gợi ý hoặc nhập biển số, khu vực và khoảng thời gian cần tra cứu.
            </span>
          </div>
        )}

        {messages.map((m) => {
          const isUser = m.role === 'user';

          if (isUser) {
            return (
              <div
                key={m.id}
                className="animate-msg"
                style={{
                  alignSelf: 'flex-end',
                  maxWidth: '72%',
                  background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
                  color: '#ffffff',
                  fontSize: '13.5px',
                  lineHeight: 1.55,
                  padding: '11px 16px',
                  borderRadius: '16px 16px 4px 16px',
                  boxShadow: '0 4px 14px rgba(37, 99, 235, 0.3)'
                }}
              >
                {m.text}
              </div>
            );
          }

          // AI Message
          return (
            <div
              key={m.id}
              className="animate-msg"
              style={{
                alignSelf: 'flex-start',
                maxWidth: '90%'
              }}
            >
              {/* AI Avatar & Title */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span
                    style={{
                      width: '24px',
                      height: '24px',
                      borderRadius: '7px',
                      background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: '0 2px 6px rgba(59, 130, 246, 0.3)'
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2">
                      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
                    </svg>
                  </span>
                  <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--ink2)' }}>Trợ lý AI</span>
                </div>

                <button
                  onClick={() => handleCopy(m.id, m.text)}
                  title="Sao chép nội dung"
                  style={{
                    backgroundColor: 'transparent',
                    border: 'none',
                    color: 'var(--ink3)',
                    cursor: 'pointer',
                    fontSize: '11px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    padding: '2px 6px',
                    borderRadius: '4px'
                  }}
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>{copiedMsgId === m.id ? 'Đã chép' : 'Sao chép'}</span>
                </button>
              </div>

              {/* Text Bubble */}
              <div
                className="glass-card"
                style={{
                  fontSize: '13.5px',
                  lineHeight: 1.6,
                  padding: '14px 18px',
                  borderRadius: '4px 16px 16px 16px',
                  color: 'var(--ink)',
                  boxShadow: 'var(--shadow-sm)',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {renderAssistantText(m.text)}
              </div>

              {/* Video Clip Card if available */}
              {m.clip && (
                <div
                  className="glass-panel"
                  style={{
                    marginTop: '10px',
                    borderRadius: '14px',
                    overflow: 'hidden',
                    maxWidth: '480px',
                    boxShadow: 'var(--shadow-md)',
                    border: '1px solid var(--line2)'
                  }}
                >
                  {/* Video Viewport Frame */}
                  <div
                    style={{
                      position: 'relative',
                      aspectRatio: '16/9',
                      background: 'radial-gradient(120% 90% at 50% 18%, #1c212b 0%, #0d1017 60%, #06080b 100%)',
                      overflow: 'hidden'
                    }}
                  >
                    <video
                      controls
                      preload="none"
                      src={resolveMediaUrl(m.clip.streamUrl)}
                      aria-label={`Clip đối chứng: ${m.clip.title}`}
                      style={{
                        width: '100%',
                        height: '100%',
                        display: 'block',
                        objectFit: 'contain',
                        backgroundColor: '#06080b',
                      }}
                    />

                    {/* Camera Name Tag */}
                    <div
                      style={{
                        position: 'absolute',
                        left: '10px',
                        top: '10px',
                        backgroundColor: 'rgba(0,0,0,0.65)',
                        backdropFilter: 'blur(4px)',
                        color: '#e3e7ea',
                        fontSize: '10px',
                        padding: '3px 8px',
                        borderRadius: '5px',
                        fontFamily: 'var(--font-mono)'
                      }}
                    >
                      {m.clip.cam}
                    </div>

                    {/* 10s Badge */}
                    <div
                      style={{
                        position: 'absolute',
                        right: '10px',
                        top: '10px',
                        backgroundColor: 'var(--p0)',
                        color: '#ffffff',
                        fontSize: '9px',
                        fontWeight: 700,
                        padding: '3px 8px',
                        borderRadius: '5px',
                        letterSpacing: '0.04em'
                      }}
                    >
                      CLIP 10s
                    </div>
                  </div>

                  {/* Player Controls & Scrubber */}
                  <div style={{ padding: '10px 14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                      <span style={{ fontSize: '10.5px', fontFamily: 'var(--font-mono)', color: 'var(--ink3)' }}>
                        {m.clip.from}
                      </span>
                      <div
                        style={{
                          flex: 1,
                          height: '5px',
                          borderRadius: '3px',
                          backgroundColor: 'var(--raise)',
                          position: 'relative'
                        }}
                      >
                        {/* Segment Highlight Marker */}
                        <div
                          style={{
                            position: 'absolute',
                            left: '30%',
                            width: '45%',
                            top: 0,
                            bottom: 0,
                            backgroundColor: `${m.clip.boxColor}55`,
                            borderLeft: `1.5px solid ${m.clip.boxColor}`,
                            borderRight: `1.5px solid ${m.clip.boxColor}`
                          }}
                        />

                        {/* Playback progress fill */}
                        <div
                          style={{
                            position: 'absolute',
                            left: 0,
                            top: 0,
                            bottom: 0,
                            width: '32%',
                            backgroundColor: 'var(--acc)',
                            borderRadius: '3px',
                            transition: 'width 1.5s linear'
                          }}
                        />

                        {/* Playhead thumb */}
                        <div
                          style={{
                            position: 'absolute',
                            left: '32%',
                            top: '50%',
                            width: '11px',
                            height: '11px',
                            borderRadius: '50%',
                            backgroundColor: '#ffffff',
                            transform: 'translate(-50%, -50%)',
                            boxShadow: '0 1px 4px rgba(0,0,0,0.6)',
                            transition: 'left 1.5s linear'
                          }}
                        />
                      </div>
                      <span style={{ fontSize: '10.5px', fontFamily: 'var(--font-mono)', color: 'var(--ink3)' }}>
                        {m.clip.to}
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '12px', color: 'var(--ink)', flex: 1, fontWeight: 500 }}>
                        {m.clip.title}
                      </span>
                      <a
                        href={resolveMediaUrl(m.clip.downloadUrl)}
                        download
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px',
                          fontSize: '11.5px',
                          fontWeight: 600,
                          padding: '5px 12px',
                          borderRadius: '7px',
                          border: '1px solid var(--line2)',
                          backgroundColor: 'var(--raise)',
                          color: 'var(--ink)',
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                          textDecoration: 'none',
                        }}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
                        </svg>
                        Tải clip 10s
                      </a>
                    </div>
                  </div>
                </div>
              )}
              {m.evidence && <ActivityEvidenceCard initial={m.evidence} />}
              {!m.clip && !m.evidence && (
                <div style={{ marginTop: '7px', color: 'var(--ink3)', fontSize: '11.5px' }}>
                  Không có clip
                </div>
              )}
            </div>
          );
        })}

        {isSending && (
          <div
            role="status"
            className="animate-msg glass-card"
            style={{
              alignSelf: 'flex-start',
              display: 'flex',
              alignItems: 'center',
              gap: '9px',
              color: 'var(--ink2)',
              fontSize: '12.5px',
              padding: '11px 14px',
              borderRadius: '4px 16px 16px 16px',
            }}
          >
            <span
              aria-hidden="true"
              style={{
                width: '13px',
                height: '13px',
                border: '2px solid var(--line2)',
                borderTopColor: 'var(--acc)',
                borderRadius: '50%',
                animation: 'qa-spin 0.8s linear infinite',
              }}
            />
            Trợ lý AI đang tra cứu dữ liệu…
          </div>
        )}

        {error && (
          <div
            role="alert"
            style={{
              alignSelf: 'stretch',
              color: 'var(--p0)',
              backgroundColor: 'color-mix(in srgb, var(--p0) 9%, transparent)',
              border: '1px solid color-mix(in srgb, var(--p0) 32%, transparent)',
              borderRadius: '10px',
              padding: '10px 12px',
              fontSize: '12.5px',
            }}
          >
            {error}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Bottom Controls Area */}
      <div style={{ flex: 'none', paddingTop: '12px' }}>
        {/* Suggested Queries Chips */}
        <div style={{ display: 'flex', gap: '7px', flexWrap: 'wrap', marginBottom: '10px' }}>
          {suggestedQuestions.map((query, i) => (
            <button
              key={i}
              onClick={() => void onSendMessage(query)}
              disabled={isSending || isHistoryLoading}
              style={{
                fontSize: '12px',
                fontWeight: 500,
                padding: '6px 14px',
                borderRadius: '20px',
                border: '1px solid var(--line2)',
                backgroundColor: 'var(--card)',
                color: 'var(--ink2)',
                cursor: isSending || isHistoryLoading ? 'not-allowed' : 'pointer',
                opacity: isSending || isHistoryLoading ? 0.55 : 1,
                fontFamily: 'inherit',
                transition: 'all 0.15s ease'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--acc)';
                e.currentTarget.style.color = 'var(--acc)';
                e.currentTarget.style.backgroundColor = 'var(--raise)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--line2)';
                e.currentTarget.style.color = 'var(--ink2)';
                e.currentTarget.style.backgroundColor = 'var(--card)';
              }}
            >
              {query}
            </button>
          ))}
        </div>

        {/* Input Bar */}
        <div
          className="glass-panel"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            borderRadius: '14px',
            padding: '5px 6px 5px 16px',
            boxShadow: 'var(--shadow-md)',
            border: '1px solid var(--line2)'
          }}
        >
          <input
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isSending || isHistoryLoading}
            placeholder="Hỏi về sự kiện camera… vd: hôm nay có bao nhiêu xe lạ vào?"
            style={{
              flex: 1,
              border: 'none',
              outline: 'none',
              backgroundColor: 'transparent',
              color: 'var(--ink)',
              fontSize: '13.5px',
              fontFamily: 'inherit',
              padding: '10px 0'
            }}
          />
          <button
            onClick={handleSend}
            disabled={!inputVal.trim() || isSending || isHistoryLoading}
            style={{
              width: '38px',
              height: '38px',
              flex: 'none',
              borderRadius: '10px',
              border: 'none',
              background: inputVal.trim() && !isSending && !isHistoryLoading
                ? 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)'
                : 'var(--raise)',
              color: '#ffffff',
              cursor: inputVal.trim() && !isSending && !isHistoryLoading ? 'pointer' : 'not-allowed',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: inputVal.trim() && !isSending && !isHistoryLoading
                ? '0 2px 10px rgba(59, 130, 246, 0.4)'
                : 'none'
            }}
          >
            {isSending ? (
              <span
                aria-hidden="true"
                style={{
                  width: '14px',
                  height: '14px',
                  border: '2px solid rgba(255,255,255,0.35)',
                  borderTopColor: '#ffffff',
                  borderRadius: '50%',
                  animation: 'qa-spin 0.8s linear infinite',
                }}
              />
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="m22 2-7 20-4-9-9-4z" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
