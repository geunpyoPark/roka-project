def make_chunks(segments):
    chunks = []
    for seg in segments:
        chunks.append({
            "text": seg["text"].strip(),
            "start": seg["start"],
            "end": seg["end"]
        })
    return chunks
