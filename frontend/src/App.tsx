// frontend/src/App.tsx

import React, { useEffect, useState } from "react";
import EmotionPanel from "./EmotionPanel";
import TranscriptPanel from "./TranscriptPanel";

const BACKEND_BASE = "http://127.0.0.1:8000";
const USER_ID = "test-user-1";

interface AnalysisResult {
  text: string;
  wpm: number | null;
  speed_label?: string | null;
  timestamp: string;
}

interface TipResult {
  summary: string;
  bullets: string[];
  speed_comment?: string | null;
}

const App: React.FC = () => {
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const [tipResult, setTipResult] = useState<TipResult | null>(null);
  const [tipLoading, setTipLoading] = useState(false);
  const [tipError, setTipError] = useState<string | null>(null);

  // ------------------ 분석 결과 폴링 ------------------
  useEffect(() => {
    let timer: number | undefined;

    const fetchLatest = async () => {
      try {
        const res = await fetch(
          `${BACKEND_BASE}/analysis/${USER_ID}/latest`
        );
        if (!res.ok) {
          setAnalysis(null);
          setAnalysisError("백엔드에 연결할 수 없습니다.");
          return;
        }
        const data = await res.json();
        setAnalysis({
          text: data.text ?? "",
          wpm: data.wpm ?? null,
          speed_label: data.speed_label ?? null,
          timestamp: data.timestamp ?? "",
        });
        setAnalysisError(null);
      } catch (err) {
        console.error(err);
        setAnalysisError("분석 결과를 불러오는 중 오류가 발생했습니다.");
      }
    };

    fetchLatest();
    timer = window.setInterval(fetchLatest, 1000);

    return () => {
      if (timer) window.clearInterval(timer);
    };
  }, []);

  // ------------------ Assist: /tips 호출 ------------------
  const handleAssistClick = async () => {
    setTipError(null);
    setTipResult(null);

    const answerText = analysis?.text || "";

    if (!answerText.trim()) {
      setTipError(
        "사용할 답변 텍스트가 없습니다. 먼저 말을 해서 STT 결과가 들어오도록 해 주세요."
      );
      return;
    }

    setTipLoading(true);
    try {
      const res = await fetch(`${BACKEND_BASE}/tips/${USER_ID}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          // 지금은 질문을 별도로 안 받으므로 공백/기본값
          question: "",
          answer_text: answerText,
          wpm: analysis?.wpm ?? null,
          speed_label:
            analysis?.wpm == null
              ? null
              : analysis.wpm < 80
              ? "조금 느림"
              : analysis.wpm > 160
              ? "조금 빠름"
              : "적당함",
        }),
      });

      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || "Tip API error");
      }

      const data: TipResult = await res.json();
      setTipResult(data);
    } catch (err: any) {
      console.error(err);
      setTipError(
        `Assist 생성 중 오류가 발생했습니다: ${err.message ?? err}`
      );
    } finally {
      setTipLoading(false);
    }
  };

  const speedLabel =
    analysis?.wpm == null
      ? "-"
      : analysis.wpm < 80
      ? "조금 느림"
      : analysis.wpm > 160
      ? "조금 빠름"
      : "적당함";

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#020617",
        color: "white",
        display: "flex",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 1180,
          padding: "24px 32px 40px",
          boxSizing: "border-box",
        }}
      >
        {/* 헤더 */}
        <header style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: 26, margin: 0, marginBottom: 4 }}>
            Interview Assist Studio
          </h1>
          <p style={{ fontSize: 12, color: "#9ca3af" }}>
            실시간 STT / 말하기 속도 / 표정 분석 + Assist 코칭을 한 화면에서 확인합니다.
          </p>
          {analysisError && (
            <div
              style={{
                marginTop: 6,
                fontSize: 12,
                color: "#fecaca",
              }}
            >
              {analysisError}
            </div>
          )}
        </header>

        {/* 상단 2열: 왼쪽 Transcript+Assist / 오른쪽 Emotion */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2.5fr)",
            gap: 24,
          }}
        >
          {/* 왼쪽: Transcript + Assist */}
          <section>
            <TranscriptPanel
              wpm={analysis?.wpm ?? null}
              speedLabel={speedLabel}
              tipResult={tipResult}
              tipLoading={tipLoading}
              tipError={tipError}
              onAssistClick={handleAssistClick}
            />
          </section>

          {/* 오른쪽: 표정 분석 */}
          <section>
            <EmotionPanel />
          </section>
        </div>
      </div>
    </div>
  );
};

export default App;