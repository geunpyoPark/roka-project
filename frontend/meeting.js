// ===============================
//  Configuration & Global Variables
// ===============================
// HTML에서 ONNX Runtime Web 라이브러리를 로드해야 합니다.
// <script src="https://cdn.jsdelivr.net/npm/onnxruntime-web/dist/ort.min.js"></script> 또는
// <script src="https://cdn.jsdelivr.net/npm/onnxruntime-web/dist/ort.webgpu.min.js"></script>

let socket;
let pc;
let localStream;
let aiStream;
let session;
let audioSocket;

// WebRTC signaling 서버 주소
const signalingURL = "ws://localhost:3001";
// FastAPI/Whisper 음성 분석 서버 주소
const audioStreamURL = "ws://localhost:8000/audio-stream";

// DOM Elements
const localVideo = document.getElementById("localVideo");
const remoteVideo = document.getElementById("remoteVideo");
const aiCam = document.getElementById("aiCam"); // 소스용 숨겨진 비디오
const aiCanvas = document.getElementById("aiCanvas"); // 결과 출력용 캔버스
const ctx = aiCanvas.getContext("2d");

// === YOLO Face Model Path ===
// 경로 확인 필수!
const YOLO_MODEL_URL = "/frontend/models/yolov8m-face-lindevs.onnx";


// ===============================
//  Audio Stream Function
// ===============================
function startAudioStream() {
    console.log("🔊 Starting Audio Stream to backend...");
    
    // WebSocket 연결 (FastAPI/Whisper 서버)
    audioSocket = new WebSocket(audioStreamURL);

    // 바이너리 데이터 전송을 위한 설정
    audioSocket.binaryType = "arraybuffer";

    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    
    // localStream (카메라/마이크에서 얻은 스트림)에서 오디오 소스 생성
    const source = audioContext.createMediaStreamSource(localStream);
    
    // ScriptProcessorNode를 사용하여 오디오 데이터 처리
    // (4096: 버퍼 크기, 1: 입력 채널, 1: 출력 채널)
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    source.connect(processor);
    processor.connect(audioContext.destination);

    // 오디오 처리 이벤트 핸들러
    processor.onaudioprocess = (event) => {
        // 첫 번째 채널의 Float32 데이터를 가져옴
        const input = event.inputBuffer.getChannelData(0);
        
        // Whisper 서버 요구에 맞게 Int16으로 변환 (정규화: -32767 ~ 32767)
        const int16Array = new Int16Array(input.length);

        for (let i = 0; i < input.length; i++) {
            // Float32 (0~1)를 Int16 (-32767~32767)로 변환
            int16Array[i] = input[i] * 32767; 
        }

        // WebSocket이 열려있다면 전송
        if (audioSocket.readyState === WebSocket.OPEN) {
            audioSocket.send(int16Array);
        }
    };
    
    audioSocket.onopen = () => console.log("🟢 Audio WebSocket Connected!");
    audioSocket.onclose = () => console.log("🔴 Audio WebSocket Closed.");
    audioSocket.onerror = (err) => console.error("❌ Audio WebSocket Error:", err);
}


// ===============================
//  1. Join Button Logic (입장)
// ===============================
document.getElementById("joinBtn").onclick = async () => {
    // 소켓 연결
    socket = new WebSocket(signalingURL);

    socket.onopen = () => console.log("🟢 Connected to signaling server");

    socket.onmessage = async (msg) => {
        const parsed = JSON.parse(msg.data);

        if (parsed.type === "welcome") {
            console.log("My ID:", parsed.id);
            return;
        }

        const { from, data } = parsed;

        // WebRTC Signaling 처리
        if (data?.sdp) {
            await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
            if (data.sdp.type === "offer") {
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                sendTo(from, { sdp: pc.localDescription });
            }
        }

        if (data?.ice) {
            await pc.addIceCandidate(data.ice);
        }
    };

    await startWebRTC();
};


// ===============================
//  2. WebRTC Start
// ===============================
async function startWebRTC() {
    try {
        // 1. 카메라 스트림 가져오기
        localStream = await navigator.mediaDevices.getUserMedia({
            video: { width: 1280, height: 720 },
            audio: true
        });

        // 2. 화면에 내 얼굴 표시
        localVideo.srcObject = localStream;

        // 3. AI 분석용 스트림 복제
        aiStream = localStream.clone();
        aiCam.srcObject = aiStream; // 숨겨진 비디오 태그에 연결
        
        // 비디오가 준비되면 AI 루프 시작
        aiCam.onloadedmetadata = () => {
            aiCam.play();
            // YOLO 모델 로드 후 AI 루프 시작
            loadYOLO().then(() => startAIScreen());
        };

        // 4. P2P 연결 설정
        pc = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });

        pc.onicecandidate = (e) => {
            if (e.candidate) sendTo("all", { ice: e.candidate });
        };

        pc.ontrack = (e) => {
            remoteVideo.srcObject = e.streams[0];
        };

        localStream.getTracks().forEach(t => pc.addTrack(t, localStream));

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        sendTo("all", { sdp: pc.localDescription });

        // ⭐⭐⭐ 추가된 부분: 음성 스트림 시작 ⭐⭐⭐
        startAudioStream();

    } catch (err) {
        console.error("Error starting WebRTC:", err);
        alert("카메라를 찾을 수 없거나 권한이 없습니다.");
    }
}


// ===============================
//  3. Signaling Helper
// ===============================
function sendTo(to, data) {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ to, data }));
    }
}


// ===============================
//  4. Load YOLO Face Model
// ===============================
async function loadYOLO() {
    console.log("🔄 Loading YOLO Model...");
    try {
        // [⭐⭐ WASM (CPU) 환경으로 고정 - 안정성 확보 ⭐⭐]
        session = await ort.InferenceSession.create(YOLO_MODEL_URL, {
            executionProviders: ["wasm"], 
            graphOptimizationLevel: "all"
        });

        console.log("=== YOLO Model Loaded Successfully (Using WASM/CPU) ===");
    } catch (e) {
        console.error("❌ 모델 로드 실패! 경로를 확인하세요:", e);
        alert("AI 모델 로드에 실패했습니다. 모델 파일 경로를 확인해 주세요.");
    }
}


// ===============================
//  5. AI Camera Loop (핵심)
// ===============================
function startAIScreen() {
    // YOLO 모델 입력 크기 (640x640 고정)
    aiCanvas.width = 640;
    aiCanvas.height = 640;

    // [⭐ 프레임 속도 제어 설정 (5 FPS) ⭐]
    const INFERENCE_INTERVAL = 200; // 200ms마다 실행 (1000ms / 200ms = 5 FPS)

    async function loop() {
        // [중요] 비디오를 캔버스에 꽉 차게 그리기 (Stretch)
        ctx.drawImage(aiCam, 0, 0, aiCanvas.width, aiCanvas.height);

        // session이 성공적으로 로드되었을 때만 추론 실행
        if (session) {
            try {
                // Preprocess: HWC -> CHW 변환
                const input = preprocess(aiCanvas);
                // 추론 실행
                const outputs = await session.run({ images: input });
                // 결과 그리기
                drawBoxes(outputs);
            } catch (e) {
                console.error("❌ Inference Error:", e);
            }
        }
        
        // requestAnimationFrame 대신 setTimeout을 사용하여 FPS 제어
        setTimeout(loop, INFERENCE_INTERVAL);
    }

    loop();
}


// ===============================
//  6. Preprocess: HWC -> CHW
// ===============================
function preprocess(canvas) {
    const w = 640;
    const h = 640;
    const imageSize = w * h;

    const imgData = ctx.getImageData(0, 0, w, h);
    const data = new Float32Array(w * h * 3);

    // HWC (R,G,B,A, R,G,B,A...) -> CHW (RRR..., GGG..., BBB...) 변환 및 정규화(0~1)
    for (let i = 0; i < imageSize; i++) {
        data[i] = imgData.data[i * 4] / 255.0;                 // R
        data[i + imageSize] = imgData.data[i * 4 + 1] / 255.0; // G
        data[i + imageSize * 2] = imgData.data[i * 4 + 2] / 255.0; // B
    }

    return new ort.Tensor("float32", data, [1, 3, h, w]);
}


// ===============================
//  7. Draw Boxes (좌표 자동 보정 & 빨간 스타일)
// ===============================
let isDebugged = false;

function drawBoxes(outputs) {
    const outName = session.outputNames[0];
    const data = outputs[outName].data; 
    const dims = outputs[outName].dims; // [1, 5, 8400]

    if (!isDebugged) {
        console.log("✅ [DEBUG] Model Output Dims:", dims);
        isDebugged = true;
    }

    const numAnchors = dims[2]; // 8400
    const rw = aiCanvas.width;  // 640
    const rh = aiCanvas.height; // 640
    const boxes = [];

    // --- 1. 박스 필터링 및 좌표 보정 ---
    let maxConf = 0; 

    for (let i = 0; i < numAnchors; i++) {
        const conf = data[i + numAnchors * 4];

        if (conf > maxConf) maxConf = conf; 
        
        if (conf < 0.25) continue; // 임계값 0.25로 하향 조정

        let cx = data[i + numAnchors * 0];
        let cy = data[i + numAnchors * 1];
        let w  = data[i + numAnchors * 2];
        let h  = data[i + numAnchors * 3];

        // [핵심 보정] 좌표가 0~1 사이(비율)이면 640을 곱해서 픽셀 좌표로 변환
        if (cx <= 1.0) {
            cx *= rw;
            cy *= rh;
            w  *= rw;
            h  *= rh;
        }

        const x1 = cx - w / 2;
        const y1 = cy - h / 2;
        const x2 = cx + w / 2;
        const y2 = cy + h / 2;

        boxes.push({ x1, y1, x2, y2, w, h, conf });
    }

    // --- 2. NMS (중복 박스 제거) ---
    const finalBoxes = nms(boxes, 0.45);
    
    // --- 3. 화면에 그리기 (요청하신 빨간색 스타일) ---
    
    // 1. 공통 그리기 설정
    ctx.lineWidth = 4;
    ctx.strokeStyle = "#FF0000";     // 빨간 테두리
    ctx.font = "bold 20px Arial";    // 폰트 설정
    ctx.textBaseline = "top";        // 글자 기준선

    finalBoxes.forEach(box => {
        // (1) 박스 테두리 그리기
        ctx.strokeRect(box.x1, box.y1, box.w, box.h);

        // (2) 텍스트 라벨 준비
        const text = `face ${Math.round(box.conf * 100)}%`;
        const padding = 6;
        const textMetrics = ctx.measureText(text);
        const textWidth = textMetrics.width;
        const textHeight = 20; 

        // (3) 라벨 배경 그리기 (빨간색)
        ctx.fillStyle = "#FF0000";
        ctx.fillRect(box.x1, box.y1 - textHeight - padding, textWidth + (padding * 2), textHeight + padding);

        // (4) 라벨 글씨 그리기 (흰색)
        ctx.fillStyle = "#FFFFFF"; // 흰색 글씨
        ctx.fillText(text, box.x1 + padding, box.y1 - textHeight - (padding / 2) + 1);
        
        // 다음 루프를 위해 색상 복구
        ctx.fillStyle = "#FF0000"; 
    });
}


// ===============================
//  8. NMS Algorithm (필수)
// ===============================
function nms(boxes, iouThreshold) {
    if (boxes.length === 0) return [];

    boxes.sort((a, b) => b.conf - a.conf);

    const selected = [];
    const active = new Array(boxes.length).fill(true);

    for (let i = 0; i < boxes.length; i++) {
        if (!active[i]) continue;

        const boxA = boxes[i];
        selected.push(boxA);

        for (let j = i + 1; j < boxes.length; j++) {
            if (!active[j]) continue;

            const boxB = boxes[j];
            const iou = calculateIoU(boxA, boxB);

            if (iou > iouThreshold) {
                active[j] = false;
            }
        }
    }
    return selected;
}

function calculateIoU(a, b) {
    const x1 = Math.max(a.x1, b.x1);
    const y1 = Math.max(a.y1, b.y1);
    const x2 = Math.min(a.x2, b.x2);
    const y2 = Math.min(a.y2, b.y2);

    const intersectionW = Math.max(0, x2 - x1);
    const intersectionH = Math.max(0, y2 - y1);
    const areaI = intersectionW * intersectionH;

    const areaA = a.w * a.h;
    const areaB = b.w * b.b;

    return areaI / (areaA + areaB - areaI);
}