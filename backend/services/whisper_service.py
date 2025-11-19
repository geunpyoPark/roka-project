from faster_whisper import WhisperModel

# base/small 권장. macOS에서 mps 자동 활성화됨.
model = WhisperModel("base", device="cpu", compute_type="float32")

def transcribe_audio(audio_bytes: bytes):
    # Faster-Whisper는 bytes 직접 입력이 가능함
    segments, _ = model.transcribe(audio_bytes, beam_size=1)
    
    text = "".join([seg.text for seg in segments])
    full_segments = [
        {"start": seg.start, "end": seg.end, "text": seg.text}
        for seg in segments
    ]

    return text, full_segments
