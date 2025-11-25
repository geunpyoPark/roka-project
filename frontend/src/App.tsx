// frontend/src/App.tsx
import React, { useCallback, useEffect, useState } from "react";
import EmotionPanel from "./EmotionPanel";
import TranscriptPanel from "./TranscriptPanel";

type AnalysisResponse = {
  user_id: string;
  text: string;
  wpm: number | null;
  speed_label: string | null;
  timestamp: number;
};

type TipResponse = {
  summary: string;
  bullets: string[];
  speed_comment?: string | null;
};

const USER_ID = "test-user-1";
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

const App: React.FC = () => {
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [lastFetchAt, setLastFetchAt] = useState<number | null>(null);

  const [question, setQuestion] = useState("");
  const [tipLoading, setTipLoading] = useState(false);
  const [tip, setTip] = useState<TipResponse | null>(null);
  const [tipError, setTipError] = useState<string | null>(null);

  const fetchLatestAnalysis = useCallback(async () => {
    try {
      setConnectionError(null);
      const res = await fetch(
        `${API_BASE}/analysis/${encodeURIComponent(USER_ID)}/latest`
      );
      if (!res.ok) {
        if (res.status === 404) {
          setAnalysis(null);
          return;
        }
        throw new Error(`HTTP ${res.status}`);
      }
      const data = (await res.json()) as AnalysisResponse;
      setAnalysis(data);
      setLastFetchAt(Date.now());
    } catch (err) {
      console.error(err);
      setConnectionError("백엔드에 연결할 수 없습니다.");
    }
  }, []);

  useEffect(() => {
    fetchLatestAnalysis();
    const id = setInterval(fetchLatestAnalysis, 500);
    return () => clearInterval(id);
  }, [fetchLatestAnalysis]);

  const handleManualRefresh = () => {
    fetchLatestAnalysis();
  };

  const handleGenerateTip = async () => {
    if (!analysis) {
      setTipError("먼저 STT 분석 결과가 필요합니다.");
      return;
    }
    setTipError(null);
    setTipLoading(true);
    try {
      const body = {
        question: question.trim() || "자기소개를 해주세요.",
        answer_text: analysis.text,
        wpm: analysis.wpm,
        speed_label: analysis.speed_label,
      };

      const res = await fetch(
        `${API_BASE}/tips/${encodeURIComponent(USER_ID)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `HTTP ${res.status}`);
      }

      const data = (await res.json()) as TipResponse;
      setTip(data);
    } catch (err: any) {
      console.error(err);
      setTipError(err.message || "피드백 생성 중 오류가 발생했습니다.");
    } finally {
      setTipLoading(false);
    }
  };

  const formatTime = (ts: number | null | undefined) => {
    if (!ts) return "-";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("ko-KR", { hour12: false });
  };

  return (
    <div
      style={{
        height: "100vh",
        maxHeight: "100vh",
        overflow: "hidden",
        background: "#020617",
        color: "#e5e7eb",
        display: "flex",
        justifyContent: "center",
        padding: "16px 0",
        boxSizing: "border-box",
      }}
    >
      <div style={{ width: 1100, maxWidth: "100%", padding: "0 16px" }}>
        {/* 헤더 */}
        <header style={{ marginBottom: 16 }}>
          <h1
            style={{
              margin: 0,
              fontSize: 24,
              fontWeight: 700,
            }}
          >
            말하기 분석 결과 뷰어 (Daglo + speech_rate)
          </h1>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 13,
              color: "#9ca3af",
            }}
          >
            whisper_worker_daglo_mic.py로 실시간 STT, speech_rate_worker.py로
            계산한 속도·라벨·피드백을 한 화면에서 확인합니다.
          </p>
        </header>

        {/* 상단: 말하기 분석 + 표정 분석 */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1.15fr) minmax(0, 1fr)",
            gap: 20,
            alignItems: "stretch",
          }}
        >
          {/* 왼쪽: 실시간 말하기 분석 카드 */}
          <section
            style={{
              background: "#020617",
              borderRadius: 16,
              border: "1px solid #1f2933",
              padding: 20,
              display: "flex",
              flexDirection: "column",
              gap: 12,
              minHeight: 320,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 4,
              }}
            >
              <div>
                <div style={{ fontWeight: 600, fontSize: 16 }}>
                  🧪 실시간 말하기 분석
                </div>
                <div style={{ fontSize: 11, color: "#9ca3af" }}>
                  한 질문에 대한 답변이 끝난 뒤 1~2초 이내에 최신 결과가
                  업데이트됩니다.
                </div>
              </div>
              <button
                onClick={handleManualRefresh}
                style={{
                  padding: "6px 10px",
                  fontSize: 12,
                  borderRadius: 999,
                  border: "1px solid #374151",
                  background: "#020617",
                  color: "#e5e7eb",
                  cursor: "pointer",
                }}
              >
                ⟳ 지금 바로 새로고침
              </button>
            </div>

            {connectionError && (
              <div
                style={{
                  background: "#7f1d1d",
                  color: "#fee2e2",
                  padding: "8px 10px",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              >
                {connectionError}
              </div>
            )}

            {!analysis && !connectionError && (
              <div
                style={{
                  background: "#111827",
                  borderRadius: 8,
                  padding: 12,
                  fontSize: 12,
                  color: "#9ca3af",
                }}
              >
                아직 분석 결과가 없습니다. 터미널에서
                <span style={{ marginLeft: 4, fontFamily: "monospace" }}>
                  whisper_worker_daglo_mic.py
                </span>
                와
                <span
                  style={{
                    marginLeft: 4,
                    fontFamily: "monospace",
                  }}
                >
                  speech_rate_worker.py
                </span>
                를 실행한 뒤 말해 보세요.
              </div>
            )}

            {analysis && (
              <div
                style={{
                  background: "#020617",
                  borderRadius: 8,
                  border: "1px solid #1f2933",
                  padding: 12,
                  fontSize: 13,
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: "#6b7280",
                    marginBottom: 6,
                  }}
                >
                  마지막 업데이트: {formatTime(analysis.timestamp)}
                </div>
                <div
                  style={{
                    maxHeight: 100,
                    overflowY: "auto",
                    paddingRight: 4,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {analysis.text}
                </div>
              </div>
            )}

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 10,
              }}
            >
              <div
                style={{
                  borderRadius: 10,
                  border: "1px solid #1f2933",
                  padding: 12,
                  fontSize: 12,
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: "#9ca3af",
                    marginBottom: 4,
                  }}
                >
                  WPM (분당 단어 수)
                </div>
                <div style={{ fontSize: 20, fontWeight: 600 }}>
                  {analysis?.wpm != null ? analysis.wpm.toFixed(1) : "-"}
                </div>
              </div>
              <div
                style={{
                  borderRadius: 10,
                  border: "1px solid #1f2933",
                  padding: 12,
                  fontSize: 12,
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: "#9ca3af",
                    marginBottom: 4,
                  }}
                >
                  속도 평가
                </div>
                <div style={{ fontSize: 20, fontWeight: 600 }}>
                  {analysis?.speed_label ?? "-"}
                </div>
              </div>
            </div>

            {/* 면접 피드백 섹션 */}
            <div
              style={{
                marginTop: 4,
                borderTop: "1px solid #1f2933",
                paddingTop: 12,
                fontSize: 12,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <div style={{ fontWeight: 600 }}>🧠 면접 피드백</div>
                <button
                  onClick={handleGenerateTip}
                  disabled={tipLoading}
                  style={{
                    padding: "6px 10px",
                    fontSize: 12,
                    borderRadius: 999,
                    border: "none",
                    background: tipLoading ? "#4b5563" : "#16a34a",
                    color: "white",
                    cursor: tipLoading ? "default" : "pointer",
                  }}
                >
                  {tipLoading ? "생성 중..." : "피드백 생성"}
                </button>
              </div>
              <div style={{ color: "#9ca3af", fontSize: 11 }}>
                최근 답변의 STT 결과와 말 속도를 기반으로 간단한 피드백을
                생성합니다. 먼저 질문에 대한 답변을 한 뒤, 위 버튼을 눌러
                보세요.
              </div>
              <div>
                <div
                  style={{
                    fontSize: 11,
                    color: "#9ca3af",
                    marginBottom: 4,
                  }}
                >
                  면접관 질문 (선택 입력)
                </div>
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="예) 자기소개를 해주세요."
                  rows={2}
                  style={{
                    width: "100%",
                    resize: "vertical",
                    minHeight: 48,
                    maxHeight: 80,
                    borderRadius: 8,
                    border: "1px solid #1f2933",
                    background: "#020617",
                    color: "#e5e7eb",
                    padding: 8,
                    fontSize: 13,
                    boxSizing: "border-box",
                  }}
                />
              </div>

              {tipError && (
                <div
                  style={{
                    background: "#7f1d1d",
                    color: "#fee2e2",
                    padding: "8px 10px",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                >
                  {tipError}
                </div>
              )}

              {tip && (
                <div
                  style={{
                    marginTop: 4,
                    borderRadius: 10,
                    border: "1px solid #1f2933",
                    padding: 12,
                    background: "#020617",
                    maxHeight: 140,
                    overflowY: "auto",
                  }}
                >
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      marginBottom: 6,
                    }}
                  >
                    {tip.summary}
                  </div>
                  {tip.speed_comment && (
                    <div
                      style={{
                        fontSize: 12,
                        color: "#eab308",
                        marginBottom: 6,
                      }}
                    >
                      ⚡ {tip.speed_comment}
                    </div>
                  )}
                  {tip.bullets?.length > 0 && (
                    <ul
                      style={{
                        paddingLeft: 18,
                        margin: 0,
                        fontSize: 12,
                        display: "flex",
                        flexDirection: "column",
                        gap: 2,
                      }}
                    >
                      {tip.bullets.map((b, idx) => (
                        <li key={idx}>{b}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </section>

          {/* 오른쪽: 표정 분석 패널 */}
          <section>
            <EmotionPanel />
          </section>
        </div>

        {/* 하단: Transcript */}
        <div style={{ marginTop: 20 }}>
          <TranscriptPanel />
        </div>
      </div>
    </div>
  );
};

export default App;