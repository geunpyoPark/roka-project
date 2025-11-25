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

const USER_ID = "test-user-1";

const TranscriptPanel: React.FC = () => {
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
          // 폴링 중 에러는 조용히 무시 (로그만)
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
  // 3) 렌더링
  // ---------------------------
  return (
    <section style={{ marginTop: 24 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 6,
        }}
      >
        <span style={{ fontSize: 14 }}>📑 Transcript</span>
      </div>
      <p style={{ fontSize: 12, color: "#9ca3af", marginBottom: 8 }}>
        실시간/사후 STT 결과를 화자별로 분리해서 보는 영역입니다.
      </p>

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
              background:
                activeTab === "chat" ? "#111827" : "transparent",
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
              fontSize: 13,
              color: "#9ca3af",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            향후 여기에 면접 보조용 Chat 기능을 넣을 예정입니다.
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
    </section>
  );
};

export default TranscriptPanel;