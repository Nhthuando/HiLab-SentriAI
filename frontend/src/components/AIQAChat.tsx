import React, { useState, useRef, useEffect } from 'react';
import type { ChatMessage } from '../types';

interface AIQAChatProps {
  messages: ChatMessage[];
  onSendMessage: (text: string) => void;
  onClearChat?: () => void;
}

export const AIQAChat: React.FC<AIQAChatProps> = ({ messages, onSendMessage, onClearChat }) => {
  const [inputVal, setInputVal] = useState<string>('');
  const [isPlayingClipId, setIsPlayingClipId] = useState<string | null>(null);
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
    if (!trimmed) return;
    onSendMessage(trimmed);
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
  }, [messages]);

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
      {messages.length > 2 && onClearChat && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '8px' }}>
          <button
            onClick={onClearChat}
            style={{
              fontSize: '11.5px',
              fontWeight: 500,
              color: 'var(--ink3)',
              backgroundColor: 'transparent',
              border: 'none',
              cursor: 'pointer',
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
                  boxShadow: 'var(--shadow-sm)'
                }}
              >
                {m.text}
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
                    {/* Simulated Background */}
                    <div
                      style={{
                        position: 'absolute',
                        left: 0,
                        right: 0,
                        bottom: 0,
                        height: '56%',
                        background: 'linear-gradient(#0c1015, #050709)',
                        backgroundImage: 'repeating-linear-gradient(90deg, rgba(255,255,255,0.05) 0 1px, transparent 1px 13%)'
                      }}
                    />

                    {/* Simulated Object Thumbnail */}
                    <div
                      style={{
                        position: 'absolute',
                        left: '28%',
                        top: '36%',
                        width: '44%',
                        height: '46%',
                        background: `linear-gradient(160deg, ${m.clip.tint}, #10141b)`,
                        borderRadius: '6px',
                        border: '1px solid rgba(255,255,255,0.1)'
                      }}
                    />

                    {/* Bounding Box on Target */}
                    <div
                      style={{
                        position: 'absolute',
                        left: '27%',
                        top: '35%',
                        width: '46%',
                        height: '48%',
                        border: `2px solid ${m.clip.boxColor}`,
                        boxShadow: `0 0 14px ${m.clip.boxColor}66`
                      }}
                    >
                      <span
                        style={{
                          position: 'absolute',
                          left: '-1px',
                          top: '-20px',
                          backgroundColor: m.clip.boxColor,
                          color: '#000000',
                          fontSize: '9.5px',
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: '4px',
                          whiteSpace: 'nowrap'
                        }}
                      >
                        {m.clip.boxLabel}
                      </span>
                    </div>

                    {/* Play Button Overlay */}
                    <button
                      onClick={() => setIsPlayingClipId(isPlayingClipId === m.id ? null : m.id)}
                      title={isPlayingClipId === m.id ? 'Tạm dừng clip' : 'Xem đoạn clip 10s'}
                      style={{
                        position: 'absolute',
                        left: '50%',
                        top: '50%',
                        transform: 'translate(-50%, -50%)',
                        width: '46px',
                        height: '46px',
                        borderRadius: '50%',
                        backgroundColor: 'rgba(0, 0, 0, 0.7)',
                        backdropFilter: 'blur(8px)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        border: '1.8px solid rgba(255, 255, 255, 0.75)',
                        boxShadow: '0 4px 16px rgba(0,0,0,0.6)'
                      }}
                    >
                      {isPlayingClipId === m.id ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="#fff">
                          <rect x="6" y="4" width="4" height="16" />
                          <rect x="14" y="4" width="4" height="16" />
                        </svg>
                      ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="#fff">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      )}
                    </button>

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
                            width: isPlayingClipId === m.id ? '75%' : '32%',
                            backgroundColor: 'var(--acc)',
                            borderRadius: '3px',
                            transition: 'width 1.5s linear'
                          }}
                        />

                        {/* Playhead thumb */}
                        <div
                          style={{
                            position: 'absolute',
                            left: isPlayingClipId === m.id ? '75%' : '32%',
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
                      <button
                        onClick={() => alert(`Bắt đầu tải đoạn video 10s (${m.clip?.title})...`)}
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
                          fontFamily: 'inherit'
                        }}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
                        </svg>
                        Tải clip 10s
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* Bottom Controls Area */}
      <div style={{ flex: 'none', paddingTop: '12px' }}>
        {/* Suggested Queries Chips */}
        <div style={{ display: 'flex', gap: '7px', flexWrap: 'wrap', marginBottom: '10px' }}>
          {suggestedQuestions.map((query, i) => (
            <button
              key={i}
              onClick={() => onSendMessage(query)}
              style={{
                fontSize: '12px',
                fontWeight: 500,
                padding: '6px 14px',
                borderRadius: '20px',
                border: '1px solid var(--line2)',
                backgroundColor: 'var(--card)',
                color: 'var(--ink2)',
                cursor: 'pointer',
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
            disabled={!inputVal.trim()}
            style={{
              width: '38px',
              height: '38px',
              flex: 'none',
              borderRadius: '10px',
              border: 'none',
              background: inputVal.trim()
                ? 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)'
                : 'var(--raise)',
              color: '#ffffff',
              cursor: inputVal.trim() ? 'pointer' : 'not-allowed',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: inputVal.trim() ? '0 2px 10px rgba(59, 130, 246, 0.4)' : 'none'
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="m22 2-7 20-4-9-9-4z" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
};
