// frontend/src/EmotionPanel.tsx

import React, { useEffect, useRef, useState } from "react";

type EmotionType = "neutral" | "happy" | "sad" | "angry" | "surprised" | "blink";

const EmotionPanel: React.FC = () => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const [status, setStatus] = useState("모델 로딩 중...");
  const [modelReady, setModelReady] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [isCalibrating, setIsCalibrating] = useState(false);

  const [emoji, setEmoji] = useState("😴");
  const [emotionText, setEmotionText] = useState("대기 중");
  const [scoreText, setScoreText] = useState("-");
  const [bars, setBars] = useState<{ name: string; value: number }[]>([]);

  // 무표정 기준 / 스무딩용 히스토리 / 보정 수집용
  const neutralBaselineRef = useRef<Record<string, number>>({});
  const blendHistoryRef = useRef<Record<string, number>>({});
  const calibrationFramesRef = useRef<any[][]>([]);
  const faceLandmarkerRef = useRef<any | null>(null);
  const animationIdRef = useRef<number | null>(null);

  // ------------------------------
  // 1) MediaPipe 모델 로드 (CDN에서 동적 import)
  // ------------------------------
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        setStatus("AI 모델 로딩 중...");

        // @ts-ignore - 원격 모듈이라 TS는 타입을 모름
        const vision = await import(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.3"
        );
        const { FaceLandmarker, FilesetResolver } = vision;

        const filesetResolver = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.3/wasm"
        );

        const lm = await FaceLandmarker.createFromOptions(filesetResolver, {
          baseOptions: {
            modelAssetPath:
              "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
            delegate: "GPU",
          },
          outputFaceBlendshapes: true,
          runningMode: "VIDEO",
          numFaces: 1,
        });

        if (cancelled) {
          lm.close();
          return;
        }

        faceLandmarkerRef.current = lm;
        setModelReady(true);
        setStatus("모델 준비 완료. 카메라를 켜세요.");
      } catch (err) {
        console.error(err);
        setStatus("모델 로딩 실패");
      }
    };

    load();

    return () => {
      cancelled = true;
      if (animationIdRef.current != null) {
        cancelAnimationFrame(animationIdRef.current);
      }
      if (faceLandmarkerRef.current) {
        faceLandmarkerRef.current.close();
      }
    };
  }, []);

  // ------------------------------
  // 2) 카메라 켜기
  // ------------------------------
  const startCamera = async () => {
    if (!modelReady) return;
    if (cameraOn) return;

    const videoEl = videoRef.current;
    if (!videoEl) return;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480 },
      });
      videoEl.srcObject = stream;
      await videoEl.play();
      setCameraOn(true);
      setStatus("분석 중...");
      startLoop();
    } catch (err) {
      console.error(err);
      setStatus("카메라 권한이 필요합니다.");
    }
  };

  // ------------------------------
  // 3) 무표정 보정 시작 / 종료
  // ------------------------------
  const startCalibration = () => {
    calibrationFramesRef.current = [];
    neutralBaselineRef.current = {};
    setIsCalibrating(true);
    setStatus("📸 3초간 무표정을 유지하세요...");

    setTimeout(() => {
      finishCalibration();
    }, 3000);
  };

  const finishCalibration = () => {
    setIsCalibrating(false);
    const frames = calibrationFramesRef.current;
    if (!frames.length) {
      setStatus("❌ 얼굴을 찾지 못했습니다. 다시 시도해주세요.");
      return;
    }

    const sum: Record<string, number> = {};
    for (const cats of frames) {
      for (const cat of cats) {
        const name = cat.categoryName;
        sum[name] = (sum[name] || 0) + cat.score;
      }
    }

    const baseline: Record<string, number> = {};
    const n = frames.length;
    for (const key in sum) {
      baseline[key] = sum[key] / n;
    }
    neutralBaselineRef.current = baseline;
    setStatus("✅ 보정 완료! 이제 표정을 지어보세요.");
  };

  // ------------------------------
  // 4) 블렌드셰이프 전처리 (스무딩 + 보정)
  // ------------------------------
  const processShapes = (rawShapes: any[]) => {
    const processed: Record<string, number> = {};
    const history = blendHistoryRef.current;
    const baseline = neutralBaselineRef.current;
    const SMOOTHING_FACTOR = 0.2;

    for (const shape of rawShapes) {
      const name = shape.categoryName as string;
      const rawValue = shape.score as number;
      const prev = history[name] ?? rawValue;
      const smoothed =
        rawValue * SMOOTHING_FACTOR + prev * (1 - SMOOTHING_FACTOR);
      history[name] = smoothed;

      let value = Math.max(0, smoothed - (baseline[name] ?? 0));
      if (value < 0.05) value = 0;
      processed[name] = value;
    }
    blendHistoryRef.current = history;
    return processed;
  };

  // ------------------------------
  // 5) 감정 추론
  // ------------------------------
  const deriveEmotion = (shapes: Record<string, number>) => {
    const get = (name: string) => shapes[name] || 0;

    const emotions: Record<EmotionType, number> = {
      neutral: 0,
      happy: ((get("mouthSmileLeft") + get("mouthSmileRight")) / 2) * 1.2,
      sad:
        (get("mouthFrownLeft") + get("mouthFrownRight") + get("browInnerUp")) /
        3,
      angry: (get("browDownLeft") + get("browDownRight")) / 2,
      surprised: (get("browInnerUp") + get("jawOpen")) / 2,
      blink: (get("eyeBlinkLeft") + get("eyeBlinkRight")) / 2,
    };

    let best: EmotionType = "neutral";
    let bestScore = 0;
    const THRESHOLD = 0.2;

    (Object.keys(emotions) as EmotionType[]).forEach((k) => {
      const v = emotions[k];
      if (v > bestScore && v > THRESHOLD) {
        best = k;
        bestScore = v;
      }
    });

    return { type: best, score: bestScore };
  };

  const updateUIFromEmotion = (emo: { type: EmotionType; score: number }) => {
    const map: Record<EmotionType, { emoji: string; text: string }> = {
      neutral: { emoji: "😐", text: "평온" },
      happy: { emoji: "😄", text: "행복" },
      sad: { emoji: "😢", text: "슬픔" },
      angry: { emoji: "😡", text: "화남" },
      surprised: { emoji: "😲", text: "놀람" },
      blink: { emoji: "👁️", text: "눈 감음" },
    };

    const info = map[emo.type];
    setEmoji(info.emoji);
    setEmotionText(info.text);
    setScoreText(`강도: ${Math.round(emo.score * 100)}%`);
  };

  // ------------------------------
  // 6) 메인 루프 (requestAnimationFrame)
  // ------------------------------
  const startLoop = () => {
    const loop = () => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      const lm = faceLandmarkerRef.current;
      if (!video || !canvas || !lm) {
        animationIdRef.current = requestAnimationFrame(loop);
        return;
      }
      if (video.readyState < 2) {
        animationIdRef.current = requestAnimationFrame(loop);
        return;
      }

      if (canvas.width !== video.videoWidth) {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
      }

      const now = performance.now();
      const results = lm.detectForVideo(video, now);
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }

      if (results.faceBlendshapes && results.faceBlendshapes.length > 0) {
        const rawShapes = results.faceBlendshapes[0].categories;

        if (isCalibrating) {
          calibrationFramesRef.current.push(rawShapes);
        } else {
          const shapes = processShapes(rawShapes);

          // 상위 몇 개를 디버그 바에 표시
          const entries = Object.entries(shapes)
            .sort(([, a], [, b]) => b - a)
            .filter(([, v]) => v > 0.01)
            .slice(0, 7)
            .map(([name, value]) => ({ name, value }));
          setBars(entries);

          const emo = deriveEmotion(shapes);
          updateUIFromEmotion(emo);
        }
      }

      animationIdRef.current = requestAnimationFrame(loop);
    };

    if (animationIdRef.current == null) {
      animationIdRef.current = requestAnimationFrame(loop);
    }
  };

  const barList = bars.map((b) => {
    const pct = Math.round(b.value * 100);
    return (
      <div
        key={b.name}
        style={{
          display: "flex",
          alignItems: "center",
          fontSize: "11px",
          marginBottom: "6px",
        }}
      >
        <span style={{ width: 120 }}>{b.name}</span>
        <div
          style={{
            flex: 1,
            height: 6,
            background: "#1f2933",
            borderRadius: 3,
            margin: "0 8px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: "100%",
              background: "#38bdf8",
              transition: "width 0.1s linear",
            }}
          />
        </div>
        <span style={{ width: 30, textAlign: "right" }}>{pct}</span>
      </div>
    );
  });

  // ------------------------------
  // 7) 레이아웃 / UI
  // ------------------------------
  return (
    <div
      style={{
        marginTop: 24,
      }}
    >
      <h2 style={{ fontSize: 16, marginBottom: 6 }}>😊 실시간 표정 분석 (MediaPipe)</h2>
      <p style={{ fontSize: 12, color: "#9ca3af", marginBottom: 10 }}>
        카메라 권한을 허용하고, 무표정 보정을 한 뒤 표정을 지어 보세요.
      </p>

      {/* 전체를 하나의 카드로 감싸기 */}
      <div
        style={{
          background: "#020617",
          borderRadius: 12,
          padding: 12,
          border: "1px solid rgba(55,65,81,0.9)",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)",
            gap: 16,
            alignItems: "stretch",
          }}
        >
          {/* 비디오 / 캔버스 영역 */}
          <div
            style={{
              position: "relative",
              borderRadius: 10,
              overflow: "hidden",
              background: "black",
              minHeight: 220,
            }}
          >
            <video
              ref={videoRef}
              muted
              autoPlay
              playsInline
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                transform: "scaleX(-1)",
                display: "block",
              }}
            />
            <canvas
              ref={canvasRef}
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                transform: "scaleX(-1)",
                pointerEvents: "none",
              }}
            />
          </div>

          {/* 오른쪽 컨트롤 / 결과 패널 */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={startCamera}
                disabled={!modelReady || cameraOn}
                style={{
                  flex: 1,
                  padding: "8px 10px",
                  borderRadius: 999,
                  border: "none",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor:
                    !modelReady || cameraOn ? "not-allowed" : "pointer",
                  background: modelReady && !cameraOn ? "#3b82f6" : "#4b5563",
                  color: "white",
                }}
              >
                {cameraOn ? "카메라 ON" : "카메라 켜기"}
              </button>
              <button
                onClick={startCalibration}
                disabled={!cameraOn}
                style={{
                  flex: 1,
                  padding: "8px 10px",
                  borderRadius: 999,
                  border: "none",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: cameraOn ? "pointer" : "not-allowed",
                  background: cameraOn ? "#f97316" : "#4b5563",
                  color: "white",
                }}
              >
                {isCalibrating ? "보정 중..." : "무표정 보정 (3초)"}
              </button>
            </div>

            <div
              style={{
                fontSize: 11,
                color: "#9ca3af",
                minHeight: 18,
                marginBottom: 4,
              }}
            >
              {status}
            </div>

            <div
              style={{
                textAlign: "center",
                padding: "10px 0",
                borderRadius: 10,
                background: "#020617",
                border: "1px solid rgba(55,65,81,0.9)",
              }}
            >
              <div style={{ fontSize: 40, marginBottom: 4 }}>{emoji}</div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{emotionText}</div>
              <div
                style={{
                  fontSize: 12,
                  color: "#9ca3af",
                  marginTop: 2,
                }}
              >
                {scoreText}
              </div>
            </div>

            <div
              style={{
                marginTop: 4,
                paddingTop: 4,
                borderTop: "1px solid rgba(31,41,55,0.9)",
                fontSize: 12,
                color: "#9ca3af",
              }}
            >
              <div style={{ marginBottom: 4 }}>📊 상위 표정 블렌드셰이프</div>
              <div style={{ maxHeight: 120, overflowY: "auto" }}>{barList}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default EmotionPanel;    