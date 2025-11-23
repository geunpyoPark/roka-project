// ====== 상태 변수 ======
let audioSocket = null;
let audioContext = null;
let processor = null;
let micStream = null;

// ====== DOM ======
const statusEl = document.getElementById("status");
const transcriptEl = document.getElementById("transcript");
const intentEl = document.getElementById("intent");
const tipEl = document.getElementById("tip");
const speechInfoEl = document.getElementById("speechInfo");

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");

// ====== 버튼 이벤트 ======
startBtn.onclick = startCoach;
stopBtn.onclick = stopCoach;

// ====== 코치 시작 ======
async function startCoach() {
  try {
    // 1) 마이크 권한 요청
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
      video: false,
    });

    statusEl.textContent = "마이크 연결 완료. 서버 접속 중...";
    startBtn.disabled = true;
    stopBtn.disabled = false;

    // 2) WebSocket 연결 (FastAPI audio-stream 엔드포인트)
    audioSocket = new WebSocket("ws://127.0.0.1:8000/audio-stream");
    audioSocket.binaryType = "arraybuffer";

    audioSocket.onopen = () => {
      statusEl.textContent =
        "오디오 스트림 전송 중 (Zoom/Meet에서 편하게 말해보세요)";
      console.log("[assistant] WebSocket opened");
      setupAudioProcessing();
    };

    // 🔥 지금은 서버 → 클라이언트 메시지는 안 쓰지만, 혹시 모를 디버깅용
    audioSocket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        console.log("[assistant] WS message from server:", msg);

        if (msg.type === "transcript") {
          transcriptEl.textContent = msg.text || "";
        }
        if (msg.type === "intent") {
          intentEl.textContent = msg.intent || "";
        }
        if (msg.type === "tip") {
          tipEl.textContent = msg.tip || "";
        }
        if (msg.type === "speech") {
          const wpm = msg.wpm ? `${msg.wpm} WPM` : "";
          const cmt = msg.comment || "";
          speechInfoEl.textContent = [wpm, cmt].filter(Boolean).join(" / ");
        }
      } catch (e) {
        // 서버에서 바이너리나 그냥 텍스트 보낼 수도 있으니, 파싱 실패는 무시
      }
    };

    audioSocket.onerror = (e) => {
      console.error("WebSocket 에러:", e);
      statusEl.textContent = "WebSocket 에러 발생";
    };

    audioSocket.onclose = () => {
      console.log("[assistant] WebSocket closed");
      statusEl.textContent = "연결 종료됨";
      cleanupAudio();
      startBtn.disabled = false;
      stopBtn.disabled = true;
    };
  } catch (err) {
    console.error(err);
    statusEl.textContent = "마이크 권한 문제 또는 장치 오류";
    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
}

// ====== 코치 중지 ======
function stopCoach() {
  if (audioSocket && audioSocket.readyState === WebSocket.OPEN) {
    audioSocket.close();
  }
  cleanupAudio();
  statusEl.textContent = "중지됨";
  startBtn.disabled = false;
  stopBtn.disabled = true;
}

// ====== 오디오 처리 셋업 ======
function setupAudioProcessing() {
  // 이미 세팅되어 있으면 무시
  if (audioContext) return;

  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioContext.createMediaStreamSource(micStream);

  const bufferSize = 4096;
  processor = audioContext.createScriptProcessor(bufferSize, 1, 1);

  source.connect(processor);
  processor.connect(audioContext.destination);

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0); // Float32Array

    // 간단한 RMS 계산 (에너지)
    let sum = 0;
    for (let i = 0; i < input.length; i++) {
      const s = input[i];
      sum += s * s;
    }
    const rms = Math.sqrt(sum / input.length);

    // 🔈 디버깅용 로그
    // console.log("[assistant] rms:", rms);

    // 너무 작은 소리는 그냥 버림 (필요하면 값 조정)
    const NOISE_GATE = 0.003; // 0.0 ~ 0.01 사이에서 취향에 맞게 조절
    if (rms < NOISE_GATE) {
      return;
    }

    const int16 = float32ToInt16(input);

    if (audioSocket && audioSocket.readyState === WebSocket.OPEN) {
      // 브라우저 WebSocket은 TypedArray도 보낼 수 있지만,
      // 확실하게 ArrayBuffer로 보내도록 buffer 사용
      audioSocket.send(int16.buffer);
      // console.log("[assistant] sent chunk:", int16.length, "samples, rms:", rms);
    }
  };
}

// ====== 정리 ======
function cleanupAudio() {
  try {
    if (processor) {
      processor.disconnect();
      processor.onaudioprocess = null;
      processor = null;
    }
    if (audioContext) {
      audioContext.close();
      audioContext = null;
    }
    if (micStream) {
      micStream.getTracks().forEach((t) => t.stop());
      micStream = null;
    }
  } catch (e) {
    console.error("오디오 정리 중 에러:", e);
  }
}

// ====== Float32 → Int16 변환 ======
function float32ToInt16(float32Array) {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    let s = float32Array[i];
    s = Math.max(-1, Math.min(1, s)); // 클리핑
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return int16Array;
}