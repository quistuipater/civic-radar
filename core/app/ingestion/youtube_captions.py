"""Ingest the Martha's Vineyard Commission's YouTube channel
(@mvcommission) as a source of meeting transcripts. Structurally similar to
app/ingestion/meeting_audio.py (Granicus podcast audio -> WhisperX), but
YouTube has already run ASR on these videos, so there's no separate
transcription step -- just downloading the auto-generated .vtt caption file
via yt-dlp and parsing it. No YouTube Data API key needed: yt-dlp's
unauthenticated extraction works fine against this public channel (verified
live 2026-09-10: 115 videos listed via flat-playlist extraction, a real
.vtt caption downloaded for video id PAWu7LcsbwE).

Writes directly to MeetingTranscript (see app/models.py), not Document --
same reasoning as meeting_audio.py: there's no PDF/HTML to archive-then-
parse, just a transcript to archive-then-link to a Meeting.

Neither listing videos nor downloading captions goes through
app/ingestion/http_client.py's fetch_url -- yt-dlp manages its own HTTP
internally and doesn't fit that helper's (url) -> httpx.Response signature,
same carve-out meeting_audio.py takes for its audio-enclosure download.
"""

import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from dateutil import parser as dateutil_parser
from sqlalchemy.orm import Session

from app.archive import archive_dir_for, now_utc, sha256_hex, write_archive_file
from app.models import Meeting, MeetingTranscript, Source

logger = logging.getLogger(__name__)

_TIMING_TAG_RE = re.compile(r"<[^>]+>")
_VTT_CUE_TIME_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})"
)


def _vtt_timestamp_to_seconds(ts: str) -> float:
    hours, minutes, seconds = ts.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _parse_vtt(vtt_text: str) -> list[dict]:
    """Parses YouTube's rolling-caption .vtt format into merged, deduped
    segments -- see this module's Task 1 docstring/plan for the cue-growth
    pattern this collapses. Each cue's *last* non-blank line is its
    fully-revealed text; consecutive cues where one's text is a prefix of
    the next's are the same growing caption and get merged into one
    segment.
    """
    raw_cues: list[tuple[float, float, str]] = []
    # Split on blank lines (double newlines) only, not lines with just whitespace.
    # YouTube VTT may have space-only lines within cues that shouldn't cause splits.
    blocks = re.split(r"\n\n", vtt_text.strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_match = _VTT_CUE_TIME_RE.search(lines[0])
        if not time_match:
            continue
        text_lines = lines[1:]
        if not text_lines:
            continue
        last_line = _TIMING_TAG_RE.sub("", text_lines[-1]).strip()
        if not last_line:
            continue
        start = _vtt_timestamp_to_seconds(time_match.group(1))
        end = _vtt_timestamp_to_seconds(time_match.group(2))
        raw_cues.append((start, end, last_line))

    segments: list[dict] = []
    for start, end, text in raw_cues:
        if segments and text.startswith(segments[-1]["text"]):
            segments[-1]["end"] = end
            segments[-1]["text"] = text
        elif segments and text == segments[-1]["text"]:
            segments[-1]["end"] = end
        else:
            segments.append({"start": start, "end": end, "text": text, "speaker": None})
    return segments
