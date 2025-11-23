// src/pages/InterviewPage.tsx
import React from "react";
import { SpeechFeedbackPanel } from "../components/SpeechFeedbackPanel";

export default function InterviewPage() {
  // 실제로는 로그인/세션 기반 userId를 사용
  const userId = "test-user-1";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      {/* 상단: 기존 인터뷰 UI (영상, 질문 등) */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {/* 기존 내용 들어가는 구역 */}
        인터뷰 UI 영역
      </div>

      {/* 하단: 말하기 피드백 */}
      <SpeechFeedbackPanel userId={userId} />
    </div>
  );
}