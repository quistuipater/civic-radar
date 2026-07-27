# WhisperX transcription service

Thin FastAPI wrapper around WhisperX (transcription + alignment + speaker
diarization). Runs on madhatter (GPU host) and is called over the network
by the main app's `ingest_meeting_audio()` -- the same pattern this project
already uses for Ollama, rather than bundling a GPU-dependent model into
the worker container.

## Deploy on madhatter

Runs as a `systemd --user` service (not Docker -- it needs direct GPU access
and the venv already set up in `/home/mgibbs/repos/whisperx`, same reasoning
as everything else in this file). Unit file:
`~/.config/systemd/user/whisperx.service` on madhatter:

```ini
[Unit]
Description=WhisperX transcription service (Ventura Civic Radar)
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/mgibbs/repos/whisperx
ExecStart=/home/mgibbs/repos/whisperx/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8091
Restart=on-failure
RestartSec=5
StandardOutput=append:/home/mgibbs/repos/whisperx/whisperx_service.log
StandardError=append:/home/mgibbs/repos/whisperx/whisperx_service.log

[Install]
WantedBy=default.target
```

`loginctl enable-linger mgibbs` is required so the user service starts at
boot even without an active login session. Manage it with:

```
systemctl --user status whisperx.service
systemctl --user restart whisperx.service
journalctl --user -u whisperx.service -f   # or tail whisperx_service.log
```

To set this up from scratch (first-time install, not already-deployed
madhatter): `pip install -r requirements.txt` (this file, copied alongside
`main.py`) inside the venv, and a HuggingFace access token already
configured via `huggingface-cli login` (needed for the gated
`pyannote/speaker-diarization-community-1` model), with that account having
accepted the model's terms on huggingface.co.

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
