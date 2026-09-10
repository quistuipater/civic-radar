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

import yt_dlp
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


_GOVERNANCE_KEYWORDS = (
    "meeting",
    "committee",
    "task force",
    "group",
    "alliance",
    "commission",
    "presentation",
    "forum",
    "hearing",
    "training",
)


def _is_governance_meeting_title(title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in _GOVERNANCE_KEYWORDS)


# Numeric dates use "/" or "-" as separator (YouTube titles use both, e.g.
# "4/17/25" and "10-8-25"); month-name dates cover titles like "Manuel
# Correllus State Task Force - June 10, 2025". Unlike meeting_audio.py's
# TITLE_DATE_RE, there's no trailing publish-date restatement in these
# titles to worry about skipping past -- the first match is the real date.
TITLE_DATE_RE = re.compile(
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Z][a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})"
)


def _parse_meeting_date_from_title(title: str) -> date | None:
    match = TITLE_DATE_RE.search(title)
    if not match:
        return None
    try:
        return dateutil_parser.parse(match.group(1)).date()
    except (ValueError, OverflowError):
        return None


def _extract_body_hint(title: str) -> str:
    match = TITLE_DATE_RE.search(title)
    prefix = title[: match.start()] if match else title
    return prefix.strip(" -").removesuffix("Meeting").strip(" -")


def _match_meeting(db: Session, source: Source, title: str) -> Meeting | None:
    meeting_date = _parse_meeting_date_from_title(title)
    if meeting_date is None:
        return None
    day_start = datetime(meeting_date.year, meeting_date.month, meeting_date.day, tzinfo=timezone.utc)
    day_end = datetime(meeting_date.year, meeting_date.month, meeting_date.day, 23, 59, 59, tzinfo=timezone.utc)
    candidates = (
        db.query(Meeting)
        .filter(Meeting.jurisdiction == source.jurisdiction, Meeting.start_time.between(day_start, day_end))
        .all()
    )
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    body_hint = _extract_body_hint(title).lower()
    for meeting in candidates:
        if meeting.body and (meeting.body.lower() in body_hint or body_hint in meeting.body.lower()):
            return meeting
    return candidates[0]  # best effort -- multiple same-day meetings, no clean body match


def _list_channel_videos(channel_url: str) -> list[dict]:
    opts = {"extract_flat": "in_playlist", "quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    return [{"id": entry["id"], "title": entry["title"]} for entry in info.get("entries", [])]


def _fetch_auto_captions(video_id: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmpdir:
        opts = {
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "vtt",
            "skip_download": True,
            "quiet": True,
            "outtmpl": str(Path(tmpdir) / "caps.%(ext)s"),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        vtt_path = Path(tmpdir) / "caps.en.vtt"
        if not vtt_path.exists():
            return None
        return vtt_path.read_text(encoding="utf-8")


def ingest_youtube_captions(db: Session, source: Source) -> int:
    """Returns the number of new transcripts created."""
    try:
        videos = _list_channel_videos(source.url)
    except Exception as exc:
        source.last_error = str(exc)[:2000]
        source.consecutive_failures += 1
        source.last_fetched_at = now_utc()
        db.commit()
        logger.warning("channel listing failed for source %s: %s", source.name, exc)
        return 0

    created = 0
    for video in videos:
        if not _is_governance_meeting_title(video["title"]):
            continue

        original_url = f"https://www.youtube.com/watch?v={video['id']}"
        existing = (
            db.query(MeetingTranscript)
            .filter(MeetingTranscript.source_id == source.id, MeetingTranscript.original_url == original_url)
            .one_or_none()
        )
        if existing:
            continue

        vtt_text = _fetch_auto_captions(video["id"])
        if vtt_text is None:
            logger.warning("no auto-captions available for %s (%s)", video["title"], video["id"])
            continue

        # Hashed together with the video id, not the raw caption text alone:
        # unlike meeting_audio.py's actual audio bytes (which in practice
        # never collide across distinct episodes), two distinct videos can
        # legitimately share near-identical short auto-caption text (e.g.
        # "Good evening everyone." openers) while still being separate
        # meetings that both deserve their own MeetingTranscript row. Tying
        # the hash to the video keeps the (source_id, content_hash) unique
        # constraint from conflating them, while still catching a literal
        # re-fetch of the same video's captions as a duplicate.
        content_hash = sha256_hex(f"{video['id']}:{vtt_text}".encode())
        existing_by_hash = (
            db.query(MeetingTranscript)
            .filter(MeetingTranscript.source_id == source.id, MeetingTranscript.content_hash == content_hash)
            .one_or_none()
        )
        if existing_by_hash:
            continue

        directory = archive_dir_for(source.jurisdiction, source.body, now_utc())
        archive_path = write_archive_file(directory, f"caption_{content_hash[:10]}.vtt", vtt_text.encode())

        segments = _parse_vtt(vtt_text)
        duration_seconds = segments[-1]["end"] if segments else None
        meeting = _match_meeting(db, source, video["title"])

        db.add(
            MeetingTranscript(
                meeting_id=meeting.id if meeting else None,
                source_id=source.id,
                title=video["title"],
                archive_path=str(archive_path),
                content_hash=content_hash,
                original_url=original_url,
                duration_seconds=duration_seconds,
                language="en",
                speaker_count=None,
                segments=segments,
                model_name="youtube-auto-caption",
            )
        )
        created += 1
        db.commit()
        logger.info(
            "ingested YouTube captions for %s: %d segment(s), matched meeting=%s",
            video["title"],
            len(segments),
            meeting.id if meeting else None,
        )

    source.last_fetched_at = now_utc()
    source.consecutive_failures = 0
    source.last_error = None
    if created:
        source.last_changed_at = now_utc()
    db.commit()
    return created
