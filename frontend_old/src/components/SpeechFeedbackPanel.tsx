// src/components/SpeechFeedbackPanel.tsx
import React from "react";
import { useSpeechFeedback } from "../hooks/useSpeechFeedback";

interface Props {
  userId: string;
}

export const SpeechFeedbackPanel: React.FC<Props> = ({ userId }) => {
  const feedback = useSpeechFeedback(userId);

  if (!feedback) {
    return (
      <div style={{ padding: "8px 12px", borderTop: "1px solid #ddd" }}>
        아직 인식된 문장이 없습니다.
      </div>
    );
  }

  return (
    <div style={{ padding: "8px 12px", borderTop: "1px solid #ddd" }}>
      <div>이번 문장: {feedback.text}</div>
      <div>말한 시간: {feedback.duration.toFixed(1)}초</div>
      <div>
        말하기 속도: {feedback.wpm.toFixed(1)} WPM ({feedback.label})
      </div>
    </div>
  );
};