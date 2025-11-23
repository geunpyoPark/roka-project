// frontend/src/App.tsx

import React, { useEffect, useState } from "react";

const BACKEND_HTTP = "http://localhost:8000";
const USER_ID = "test-user-1";
const ANALYSIS_URL = `${BACKEND_HTTP}/analysis/${USER_ID}/latest`;

type AnalysisData = {
  user_id: string;
  timestamp: number;
  duration: number;
  text: string;
  wpm?: number;
  label?: string;
  feedback?: string;
};

// 라벨별 색상 매핑
function getLabelColors(label?: string) {
  const base = {
    bg: "#020617",
    border: "rgba(55,65,81,0.9)",
    text: "#e5e7eb",
    chipBg: "rgba(15,23,42,0.9)",
    chipText: "#e5e7eb",
  };

  if (!label) return base;

  switch (label.trim()) {
    case "너무 빠름":
      return {
        ...base,
        bg: "#451a03",
        border: "rgba(249,115,22,0.9)",
        text: "#fed7aa",
        chipBg: "rgba(248,113,22,0.2)",
        chipText: "#fdba74",
      };
    case "조금 빠름":
      return {
        ...base,
        bg: "#422006",
        border: "rgba(234,179,8,0.9)",
        text: "#fef9c3",
        chipBg: "rgba(234,179,8,0.2)",
        chipText: "#facc15",
      };
    case "적당함":
      return {
        ...base,
        bg: "#022c22",
        border: "rgba(34,197,94,0.9)",
        text: "#bbf7d0",
        chipBg: "rgba(34,197,94,0.2)",
        chipText: "#4ade80",
      };
    case "조금 느림":
      return {
        ...base,
        bg: "#0b1120",
        border: "rgba(59,130,246,0.9)",
        text: "#bfdbfe",
        chipBg: "rgba(59,130,246,0.2)",
        chipText: "#60a5fa",
      };
    case "너무 느림":
      return {
        ...base,
        bg: "#020617",
        border: "rgba(129,140,248,0.9)",
        text: "#e0e7ff",
        chipBg: "rgba(129,140,248,0.2)",
        chipText: "#a5b4fc",
      };
    default:
      return base;
  }
}

function App() {
  const [data, setData] = useState<AnalysisData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAnalysis = async () => {
    try {
      setError(null);
      const res = await fetch(ANALYSIS_URL);
      if (!res.ok) {
        if (res.status === 404) {
          setData(null);
          return;
        }
        throw new Error(`HTTP ${res.status}`);
      }
      const json = (await res.json()) as AnalysisData;
      setData(json);
    } catch (e: any) {
      console.error("분석 결과 조회 실패:", e);
      setError("백엔드에 연결할 수 없습니다.");
    }
  };

  // 2초마다 자동 폴링
  useEffect(() => {
    fetchAnalysis();
    const timer = setInterval(fetchAnalysis, 2000);
    return () => clearInterval(timer);
  }, []);

  const labelColors = getLabelColors(data?.label);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#020617",
        color: "white",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        padding: "24px",
        fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: "720px",
          background: "#020617",
          borderRadius: "16px",
          padding: "24px 28px 32px",
          boxShadow: "0 24px 48px rgba(15,23,42,0.8)",
          border: "1px solid rgba(148,163,184,0.4)",
        }}
      >
        <h1 style={{ fontSize: "22px", fontWeight: 700, marginBottom: "8px" }}>
          말하기 분석 결과 뷰어 (Daglo + speech_rate)
        </h1>
        <p style={{ fontSize: "13px", color: "#9ca3af", marginBottom: "16px" }}>
          whisper_worker_daglo_mic.py 로 말하면, speech_rate_worker.py 가 계산한 속도·라벨·피드백을 보여줍니다.
        </p>

        <button
          onClick={fetchAnalysis}
          style={{
            padding: "6px 14px",
            borderRadius: "999px",
            border: "1px solid rgba(148,163,184,0.8)",
            background: "#111827",
            color: "white",
            fontSize: "13px",
            cursor: "pointer",
            marginBottom: "16px",
          }}
        >
          🔄 지금 바로 새로고침
        </button>

        {error && (
          <div
            style={{
              marginBottom: "12px",
              padding: "10px 12px",
              borderRadius: "8px",
              background: "#7f1d1d",
              fontSize: "13px",
            }}
          >
            {error}
          </div>
        )}

        {/* 문장 박스 */}
        <div
          style={{
            padding: "14px 14px",
            borderRadius: "10px",
            background: "#020617",
            border: "1px solid rgba(55,65,81,0.9)",
            minHeight: "80px",
            fontSize: "14px",
            whiteSpace: "pre-wrap",
            marginBottom: "14px",
          }}
        >
          {data?.text
            ? data.text
            : "아직 분석 결과가 없습니다.\n터미널에서 whisper_worker_daglo_mic.py + speech_rate_worker.py 를 실행하고 말을 해 보세요."}
        </div>

        {/* WPM & 라벨 카드 */}
        <div style={{ display: "flex", gap: "12px", marginBottom: "14px", fontSize: "13px" }}>
          <div
            style={{
              flex: 1,
              background: "#020617",
              borderRadius: "8px",
              border: "1px solid rgba(55,65,81,0.9)",
              padding: "8px 10px",
            }}
          >
            <div style={{ color: "#9ca3af", marginBottom: "4px" }}>WPM (분당 단어 수)</div>
            <div style={{ fontSize: "18px", fontWeight: 700 }}>
              {data?.wpm != null ? data.wpm.toFixed(1) : "-"}
            </div>
          </div>

          {/* 라벨 카드 - 색상 동적 변경 */}
          <div
            style={{
              flex: 1,
              borderRadius: "8px",
              padding: "8px 10px",
              background: labelColors.bg,
              border: `1px solid ${labelColors.border}`,
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <div style={{ color: "#9ca3af", marginBottom: "2px" }}>속도 평가</div>
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                alignSelf: "flex-start",
                padding: "2px 10px",
                borderRadius: "999px",
                background: labelColors.chipBg,
                color: labelColors.chipText,
                fontSize: "12px",
                fontWeight: 600,
              }}
            >
              {data?.label ? data.label : "분석 대기중"}
            </div>
            <div
              style={{
                fontSize: "11px",
                color: labelColors.text,
                marginTop: "2px",
              }}
            >
              {data?.label
                ? "라벨 색을 보고 한눈에 속도를 확인해 보세요."
                : "아직 분석 라벨이 없습니다."}
            </div>
          </div>
        </div>

        {/* 피드백 영역 (있으면 사용, 없으면 안내 문구) */}
        <div
          style={{
            marginTop: "4px",
            padding: "10px 12px",
            borderRadius: "10px",
            border: "1px dashed rgba(75,85,99,0.9)",
            background: "#020617",
            fontSize: "13px",
          }}
        >
          <div style={{ marginBottom: "4px", color: "#9ca3af", fontSize: "12px" }}>면접 피드백</div>
          <div style={{ fontSize: "13px", color: "#e5e7eb" }}>
            {data?.feedback
              ? data.feedback
              : "말하기 분석 결과가 들어오면, 이 구간에 현재 스타일 피드백이 표시됩니다."}
          </div>
        </div>

        <div style={{ marginTop: "10px", fontSize: "11px", color: "#6b7280" }}>
          {data?.timestamp && (
            <>마지막 업데이트: {new Date(data.timestamp * 1000).toLocaleTimeString()}</>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;