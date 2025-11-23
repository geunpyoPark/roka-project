// src/hooks/useSpeechFeedback.ts
import { useEffect, useState } from "react";

export type SpeechFeedback = {
  user_id: string;
  timestamp: number;
  duration: number;
  text: string;
  wpm: number;
  label: string;
};

export function useSpeechFeedback(userId: string) {
  const [lastFeedback, setLastFeedback] = useState<SpeechFeedback | null>(null);

  useEffect(() => {
    if (!userId) return;

    // 백엔드 주소/포트에 맞게 수정
    const ws = new WebSocket(`ws://localhost:8000/ws/speech/${userId}`);

    ws.onopen = () => {
      console.log("[useSpeechFeedback] WebSocket opened");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SpeechFeedback;
        setLastFeedback(data);
      } catch (e) {
        console.error("[useSpeechFeedback] Failed to parse message", e);
      }
    };

    ws.onclose = () => {
      console.log("[useSpeechFeedback] WebSocket closed");
    };

    ws.onerror = (err) => {
      console.error("[useSpeechFeedback] WebSocket error", err);
    };

    return () => {
      ws.close();
    };
  }, [userId]);

  return lastFeedback;
}