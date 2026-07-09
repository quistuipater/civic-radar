# WhisperX transcription service

Thin FastAPI wrapper around WhisperX (transcription + alignment + speaker
diarization). Runs on madhatter (GPU host) and is called over the network
by the main app's `ingest_meeting_audio()` -- the same pattern this project
already uses for Ollama, rather than bundling a GPU-dependent model into
the worker container.

## Deploy on madhatter

```
cd /home/mgibbs/repos/whisperx
source venv/bin/activate
pip install -r requirements.txt   # this file, copied alongside main.py
uvicorn main:app --host 0.0.0.0 --port 8091
```

Requires the HuggingFace access token already configured via
`huggingface-cli login` (needed for the gated
`pyannote/speaker-diarization-community-1` model) and that the account has
accepted that model's terms on huggingface.co.

## API

- `GET /health` -- readiness check, confirms models are loaded.
- `POST /transcribe` -- multipart form upload, field name `audio`.
  Optional `min_speakers`/`max_speakers` query params (pyannote's
  diarization is more accurate with a known bound on speaker count, e.g. a
  5-member commission). Returns
  `{"language": "en", "segments": [{"start", "end", "text", "speaker"}, ...]}`.

Models load once at startup and stay resident -- first request after
startup pays no extra cost beyond the normal per-file processing time
(~14x realtime on the RTX 5060 Ti, i.e. roughly 4-5s of processing per
minute of audio).
