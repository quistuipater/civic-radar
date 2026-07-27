"""Thin HTTP wrapper around WhisperX (transcription + alignment + speaker
diarization), meant to run on a GPU host (madhatter) and be called over the
network by the main app -- the same pattern this project already uses for
Ollama, rather than embedding a GPU-dependent model directly into the
worker container. Models are loaded once at process startup and kept in
memory across requests (the WhisperX CLI reloads everything per invocation,
which is fine for a one-off but wasteful for a long-running service polled
repeatedly by the ingestion worker).

Run with: uvicorn main:app --host 0.0.0.0 --port 8090
"""

import logging
import os
import tempfile

import torch
import whisperx
from fastapi import FastAPI, HTTPException, UploadFile
from whisperx.diarize import DiarizationPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("WHISPERX_MODEL", "large-v3")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = os.environ.get("WHISPERX_COMPUTE_TYPE", "float16" if DEVICE == "cuda" else "int8")
BATCH_SIZE = int(os.environ.get("WHISPERX_BATCH_SIZE", "16"))
DIARIZE_MODEL = "pyannote/speaker-diarization-community-1"

app = FastAPI(title="WhisperX transcription service")

_state: dict = {}


@app.on_event("startup")
def load_models() -> None:
    logger.info("loading ASR model %s on %s (%s)", MODEL_NAME, DEVICE, COMPUTE_TYPE)
    _state["asr_model"] = whisperx.load_model(MODEL_NAME, DEVICE, compute_type=COMPUTE_TYPE)
    logger.info("loading alignment model")
    _state["align_model"], _state["align_metadata"] = whisperx.load_align_model(language_code="en", device=DEVICE)
    logger.info("loading diarization pipeline %s", DIARIZE_MODEL)
    _state["diarize_model"] = DiarizationPipeline(model_name=DIARIZE_MODEL, device=DEVICE)
    logger.info("all models loaded, ready to serve")


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "model": MODEL_NAME, "models_loaded": bool(_state)}


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
):
    if not _state:
        raise HTTPException(status_code=503, detail="models still loading, try again shortly")

    suffix = os.path.splitext(audio.filename or "")[1] or ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name

    try:
        audio_array = whisperx.load_audio(tmp_path)

        result = _state["asr_model"].transcribe(audio_array, batch_size=BATCH_SIZE)
        detected_language = result.get("language")

        result = whisperx.align(
            result["segments"], _state["align_model"], _state["align_metadata"], audio_array, DEVICE
        )

        diarize_kwargs = {}
        if min_speakers is not None:
            diarize_kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            diarize_kwargs["max_speakers"] = max_speakers
        diarize_segments = _state["diarize_model"](audio_array, **diarize_kwargs)
        result = whisperx.assign_word_speakers(diarize_segments, result)

        return {
            "language": detected_language,
            "segments": [
                {
                    "start": seg.get("start"),
                    "end": seg.get("end"),
                    "text": seg.get("text", "").strip(),
                    "speaker": seg.get("speaker"),
                }
                for seg in result["segments"]
            ],
        }
    finally:
        os.unlink(tmp_path)
