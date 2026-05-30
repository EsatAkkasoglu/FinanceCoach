"""Voice input — POST /audio/transcribe.

Takes a short audio blob recorded in the browser (MediaRecorder → webm/ogg),
sends it to Gemini for transcription, and returns plain text the chat input
can drop in. One-shot multimodal call; no agent orchestration.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.settings import settings

log = logging.getLogger("fincoach.audio")

router = APIRouter(prefix="/audio", tags=["audio"])

# Browsers emit webm/ogg from MediaRecorder; allow the common Gemini-supported set.
SUPPORTED_AUDIO_MIME = frozenset({
    "audio/webm", "audio/ogg", "audio/wav", "audio/x-wav",
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a", "audio/aac", "audio/flac",
})

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15 MB — well above any short voice note

TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim. The speaker is asking a personal-finance "
    "question and may mix Turkish and English, and mention tickers, fund codes, "
    "or amounts. Output ONLY the transcript text — no preamble, no quotes, no "
    "translation. If the audio is silent or unintelligible, output an empty string."
)


class TranscriptionResult(BaseModel):
    text: str


@router.post("/transcribe", response_model=TranscriptionResult)
async def transcribe_audio(
    file: UploadFile = File(...),
    _user_id: int = Depends(get_current_user_id),
) -> TranscriptionResult:
    """Transcribe a short recorded audio clip to text via Gemini."""
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in SUPPORTED_AUDIO_MIME:
        raise HTTPException(status_code=415, detail=f"unsupported audio type: {mime or 'unknown'}")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio exceeds 15 MB limit")

    if not settings.gemini_api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    audio_part = types.Part.from_bytes(data=data, mime_type=mime)
    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[audio_part, TRANSCRIBE_PROMPT],
            config=types.GenerateContentConfig(temperature=0.0),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("audio transcription failed: %s", exc)
        raise HTTPException(status_code=502, detail="transcription failed") from exc

    text = (getattr(response, "text", "") or "").strip()
    return TranscriptionResult(text=text)
