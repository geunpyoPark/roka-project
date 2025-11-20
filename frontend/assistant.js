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
      statusEl.textContent = "오디오 스트림 전송 중 (Zoom/Meet에서 편하게 말해보세요)";
      setupAudioProcessing();
    };

    audioSocket.onmessage = (event) => {
      // 백엔드에서 보내주는 JSON 메시지 처리
      try {
        const msg = JSON.parse(event.data);

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
          // 예: { type:"speech", wpm:120, comment:"조금만 천천히" }
          const wpm = msg.wpm ? `${msg.wpm} WPM` : "";
          const cmt = msg.comment || "";
          speechInfoEl.textContent = [wpm, cmt].filter(Boolean).join(" / ");
        }
        // 필요하면 하나의 메시지에 다 담아서 보내도 되고, 타입 안 쓰고 field 존재 여부로도 처리 가능
      } catch (e) {
        console.error("메시지 파싱 실패:", e, event.data);
      }
    };

    audioSocket.onerror = (e) => {
      console.error("WebSocket 에러:", e);
      statusEl.textContent = "WebSocket 에러 발생";
    };

    audioSocket.onclose = () => {
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

  // ScriptProcessor는 deprecated지만, 구현 단순해서 현재 목적에는 충분
  const bufferSize = 4096;
  processor = audioContext.createScriptProcessor(bufferSize, 1, 1);

  source.connect(processor);
  processor.connect(audioContext.destination);

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0); // Float32Array
    const int16 = float32ToInt16(input);

    if (audioSocket && audioSocket.readyState === WebSocket.OPEN) {
      audioSocket.send(int16);
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