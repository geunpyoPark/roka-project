// frontend/src/TranscriptPanel.tsx
import React, { useEffect, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

type Speaker = "interviewer" | "candidate";

export interface TranscriptItem {
  id: number;
  user_id: string;
  speaker: Speaker;
  text: string;
  start_ts?: number;
  end_ts?: number;
  created_at: number;
}

interface TipResult {
  summary: string;
  bullets: string[];
  speed_comment?: string | null;
}

interface TranscriptPanelProps {
  wpm?: number | null;
  speedLabel?: string;
  tipResult?: TipResult | null;
  tipLoading?: boolean;
  tipError?: string | null;
  onAssistClick?: () => void;
}

const USER_ID = "test-user-1";

const TranscriptPanel: React.FC<TranscriptPanelProps> = ({
  wpm,
  speedLabel,
  tipResult,
  tipLoading,
  tipError,
  onAssistClick,
}) => {
  const [activeTab, setActiveTab] = useState<"chat" | "transcript">(
    "transcript"
  );
  const [items, setItems] = useState<TranscriptItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 마지막으로 받은 id (증분 가져오기용)
  const lastIdRef = useRef<number | null>(null);
  const pollingTimerRef = useRef<number | null>(null);

  // ---------------------------
  // 1) 초기 로딩 + 폴링 설정
  // ---------------------------
  useEffect(() => {
    let cancelled = false;

    const fetchInitial = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE}/transcript/${USER_ID}`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const data: TranscriptItem[] = await res.json();
        if (cancelled) return;

        setItems(data);
        if (data.length > 0) {
          lastIdRef.current = data[data.length - 1].id;
        }
        setError(null);
      } catch (e: any) {
        if (!cancelled) {
          console.error(e);
          setError("Transcript를 불러오지 못했습니다.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    const startPolling = () => {
      if (pollingTimerRef.current != null) return;

      pollingTimerRef.current = window.setInterval(async () => {
        try {
          let url = `${API_BASE}/transcript/${USER_ID}`;
          if (lastIdRef.current != null) {
            url += `?since_id=${lastIdRef.current}`;
          }

          const res = await fetch(url);
          if (!res.ok) return;
          const data: TranscriptItem[] = await res.json();
          if (!data.length) return;

          setItems((prev) => [...prev, ...data]);
          lastIdRef.current = data[data.length - 1].id;
        } catch (e) {
          console.warn("polling error", e);
        }
      }, 1000); // 1초마다 증분 조회
    };

    fetchInitial().then(startPolling);

    return () => {
      cancelled = true;
      if (pollingTimerRef.current != null) {
        window.clearInterval(pollingTimerRef.current);
      }
    };
  }, []);

  // ---------------------------
  // 2) 말풍선 렌더링
  // ---------------------------
  const renderBubble = (item: TranscriptItem) => {
    const isCandidate = item.speaker === "candidate";
    const align = isCandidate ? "flex-end" : "flex-start";
    const bg = isCandidate ? "#0f172a" : "#020617";
    const label = isCandidate ? "지원자" : "면접관";

    return (
      <div
        key={item.id}
        style={{
          display: "flex",
          justifyContent: align,
          marginBottom: 8,
        }}
      >
        <div
          style={{
            maxWidth: "60%",
            background: bg,
            borderRadius: 12,
            padding: "8px 10px",
            border: "1px solid rgba(51,65,85,0.9)",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "#9ca3af",
              marginBottom: 4,
              textAlign: isCandidate ? "right" : "left",
            }}
          >
            {label}
          </div>
          <div style={{ fontSize: 13, color: "#e5e7eb", whiteSpace: "pre-wrap" }}>
            {item.text}
          </div>
        </div>
      </div>
    );
  };

  const transcriptBody = (() => {
    if (loading && items.length === 0) {
      return (
        <div
          style={{
            fontSize: 13,
            color: "#9ca3af",
            textAlign: "center",
            paddingTop: 40,
          }}
        >
          Transcript 불러오는 중...
        </div>
      );
    }

    if (error && items.length === 0) {
      return (
        <div
          style={{
            fontSize: 13,
            color: "#f97373",
            textAlign: "center",
            paddingTop: 40,
          }}
        >
          {error}
        </div>
      );
    }

    if (!items.length) {
      return (
        <div
          style={{
            fontSize: 13,
            color: "#6b7280",
            textAlign: "center",
            paddingTop: 40,
          }}
        >
          아직 대화 내용이 없습니다.
          <br />
          나중에 STT 워커에서 자동으로 채워질 예정입니다.
        </div>
      );
    }

    return items.map(renderBubble);
  })();

  // ---------------------------
  // Assist 버튼 핸들러
  // ---------------------------
  const handleAssistClick = () => {
    if (onAssistClick) {
      onAssistClick();
      setActiveTab("chat"); // 누르면 자동으로 Chat 탭으로 전환
    }
  };

  // ---------------------------
  // 3) 렌더링
  // ---------------------------
  return (
    <section style={{ marginTop: 0 }}>
      {/* 상단 제목 + Assist 버튼 (따로) */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 6,
        }}
      >
        <span style={{ fontSize: 14 }}>📑 Transcript / Chat</span>

        <button
          onClick={handleAssistClick}
          disabled={tipLoading || !onAssistClick}
          style={{
            padding: "6px 12px",
            borderRadius: 999,
            border: "1px solid rgba(148,163,184,0.9)",
            background: tipLoading ? "#4b5563" : "#111827",
            color: "white",
            fontSize: 12,
            cursor:
              tipLoading || !onAssistClick ? "not-allowed" : "pointer",
          }}
        >
          {tipLoading ? "Assist 생성 중..." : "Assist"}
        </button>
      </div>

      <p style={{ fontSize: 12, color: "#9ca3af", marginBottom: 8 }}>
        실시간 STT를 화자별로 분리해서 보고, Assist로 다음 답변 스크립트를
        받아볼 수 있는 영역입니다.
      </p>

      {/* 메인 카드 */}
      <div
        style={{
          borderRadius: 12,
          background: "#020617",
          border: "1px solid rgba(31,41,55,0.9)",
          padding: 12,
        }}
      >
        {/* 탭 */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            marginBottom: 8,
            gap: 4,
          }}
        >
          <button
            onClick={() => setActiveTab("chat")}
            style={{
              padding: "4px 10px",
              fontSize: 12,
              borderRadius: 999,
              border: "1px solid rgba(75,85,99,0.9)",
              background: activeTab === "chat" ? "#111827" : "transparent",
              color: activeTab === "chat" ? "#e5e7eb" : "#9ca3af",
              cursor: "pointer",
            }}
          >
            Chat
          </button>
          <button
            onClick={() => setActiveTab("transcript")}
            style={{
              padding: "4px 10px",
              fontSize: 12,
              borderRadius: 999,
              border: "1px solid rgba(75,85,99,0.9)",
              background:
                activeTab === "transcript" ? "#111827" : "transparent",
              color: activeTab === "transcript" ? "#e5e7eb" : "#9ca3af",
              cursor: "pointer",
            }}
          >
            Transcript
          </button>
        </div>

        {/* 탭 내용 */}
        {activeTab === "chat" ? (
          <div
            style={{
              minHeight: 180,
              maxHeight: 260,
              overflowY: "auto",
              padding: "4px 2px",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {tipError && (
              <div
                style={{
                  fontSize: 12,
                  color: "#fecaca",
                  background: "#7f1d1d",
                  borderRadius: 8,
                  padding: "8px 10px",
                }}
              >
                {tipError}
              </div>
            )}

            {tipResult && (
              <div
                style={{
                  borderRadius: 10,
                  border: "1px solid rgba(55,65,81,0.9)",
                  background: "#020617",
                  padding: "10px 12px",
                  fontSize: 12,
                  color: "#e5e7eb",
                }}
              >
                <div
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    marginBottom: 4,
                    color: "#facc15",
                  }}
                >
                  🧭 Assist 코칭
                </div>
                <div style={{ marginBottom: 6, whiteSpace: "pre-wrap" }}>
                  {tipResult.summary}
                </div>
                {tipResult.bullets?.length > 0 && (
                  <ul
                    style={{
                      paddingLeft: 16,
                      margin: 0,
                      marginBottom: 4,
                    }}
                  >
                    {tipResult.bullets.map((b, idx) => (
                      <li key={idx} style={{ marginBottom: 2 }}>
                        {b}
                      </li>
                    ))}
                  </ul>
                )}
                {tipResult.speed_comment && (
                  <div
                    style={{
                      marginTop: 4,
                      fontSize: 11,
                      color: "#9ca3af",
                    }}
                  >
                    속도 코멘트: {tipResult.speed_comment}
                  </div>
                )}
              </div>
            )}

            {!tipResult && !tipError && !tipLoading && (
              <div
                style={{
                  fontSize: 12,
                  color: "#6b7280",
                  marginTop: 8,
                }}
              >
                아직 Assist 결과가 없습니다. 상단의{" "}
                <strong>Assist</strong> 버튼을 눌러 스크립트를 생성해 보세요.
              </div>
            )}

            {tipLoading && (
              <div
                style={{
                  fontSize: 12,
                  color: "#9ca3af",
                  marginTop: 8,
                }}
              >
                Assist 스크립트를 생성하는 중입니다...
              </div>
            )}
          </div>
        ) : (
          <div
            style={{
              minHeight: 180,
              maxHeight: 260,
              overflowY: "auto",
              padding: "4px 2px",
            }}
          >
            {transcriptBody}
          </div>
        )}
      </div>

      {/* ▼ Transcript 아래에 작게 WPM / 속도 평가 표시 */}
      <div
        style={{
          marginTop: 6,
          fontSize: 11,
          color: "#9ca3af",
          display: "flex",
          gap: 16,
        }}
      >
        <span>
          말하기 속도:&nbsp;
          {wpm != null ? `${wpm.toFixed(1)} WPM` : "-"}
        </span>
        <span>속도 평가: {speedLabel || "-"}</span>
      </div>
    </section>
  );
};

export default TranscriptPanel;