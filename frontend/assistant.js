// ====== 상태 변수 ======
let audioSocket = null;
let audioContext = null;
let processor = null;
let micStream = null;

// 분석 결과 수신용 WebSocket
let eventsSocket = null;

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

      // 🔹 분석 이벤트 수신용 WebSocket 같이 연결
      //   user_id는 현재 speech_worker / whisper_worker에서 쓰는 것과 맞추기 (예: "test-user-1")
      eventsSocket = new WebSocket("ws://127.0.0.1:8000/coach-events/test-user-1");

      eventsSocket.onopen = () => {
        console.log("coach-events WebSocket opened");
      };

      eventsSocket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          // console.log("coach-events msg:", msg);

          if (msg.type === "speech") {
            // 예: { type:"speech", wpm, label, duration, text }
            const wpm = msg.wpm ? `${Math.round(msg.wpm)} WPM` : "";
            const label = msg.label || "";
            speechInfoEl.textContent = [wpm, label].filter(Boolean).join(" / ");

            // 분석 결과에 text가 같이 들어오면 transcript에도 반영
            if (msg.text) {
              transcriptEl.textContent = msg.text;
            }
          } else if (msg.type === "transcript") {
            // 순수 STT 텍스트만 따로 오는 경우
            transcriptEl.textContent = msg.text || "";
          } else if (msg.type === "intent") {
            intentEl.textContent = msg.intent || "";
          } else if (msg.type === "tip") {
            tipEl.textContent = msg.tip || "";
          }
        } catch (e) {
          console.error("coach-events 메시지 파싱 실패:", e, event.data);
        }
      };

      eventsSocket.onerror = (e) => {
        console.error("coach-events WebSocket 에러:", e);
      };

      eventsSocket.onclose = () => {
        console.log("coach-events WebSocket closed");
      };
    };

    audioSocket.onerror = (e) => {
      console.error("audio-stream WebSocket 에러:", e);
      statusEl.textContent = "WebSocket 에러 발생";
    };

    audioSocket.onclose = () => {
      statusEl.textContent = "연결 종료됨";
      cleanupAudio();

      // 분석 WS도 같이 정리
      if (eventsSocket && eventsSocket.readyState === WebSocket.OPEN) {
        eventsSocket.close();
      }
      eventsSocket = null;

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
  audioSocket = null;

  if (eventsSocket && eventsSocket.readyState === WebSocket.OPEN) {
    eventsSocket.close();
  }
  eventsSocket = null;

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