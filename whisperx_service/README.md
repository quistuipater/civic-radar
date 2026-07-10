# WhisperX transcription service

Thin FastAPI wrapper around WhisperX (transcription + alignment + speaker
diarization), meant to run standalone on a GPU host and be called over the
network by `ingest_meeting_audio()` -- the same pattern this project already
uses for Ollama, rather than bundling a GPU-dependent model into the worker
container.

**Not deployed for Boston yet.** This directory was forked from Ventura
Civic Radar, where an identical service already runs on `madhatter.local:8091`
via a `systemd --user` unit (see that project's `whisperx_service/README.md`
for the working unit file/deployment steps to copy). No Boston meeting-audio
source has been identified yet (see this repo's README TODO section), so
there's nothing to transcribe until one is. If/when you do wire one in:
**do not reuse port 8091 or the `~/repos/whisperx` directory** on madhatter
for another instance -- Ventura's real deployment is already there, and a
third civic-radar fork (Santa Cruz) has already claimed the "if you deploy
one, don't collide with Ventura's" warning without actually deploying
anything either. Either point Boston's `WHISPERX_BASE_URL` at the existing
Ventura instance (fine if it's not saturated) or deploy a separate copy on
its own port with its own systemd unit name.

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
