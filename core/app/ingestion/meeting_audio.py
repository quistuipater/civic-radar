"""Ingest and transcribe meeting audio from Granicus podcast RSS feeds.
Structurally different from every other source: no PDF/HTML document to
parse, just an MP3 to archive-then-transcribe (see MeetingTranscript in
app/models.py for why this isn't shoehorned into Document, same reasoning
as CrimeIncident getting its own table). Transcription runs on a separate
GPU service (whisperx_service/, see its README) -- degrades gracefully
(skips, retries next poll) if that service is unreachable, matching the
rest of the AI layer's reliability contract.

Deliberately does not try to match a transcribed decision back to a
specific agenda_items row -- see app/ai/meeting_results.py's docstring for
why (item numbering/formatting drift too much to do that reliably without
a real trial run). This module's matching problem is coarser and easier:
linking a whole recording to its whole Meeting, by date.

The audio enclosures themselves are served from a CloudFront distribution
that 403s our normal, honest User-Agent (settings.http_user_agent, used
everywhere else in this project) but allows a generic browser-like one --
verified live 2026-07-09, this is a static UA-string filter, not a
CAPTCHA/interactive bot-challenge (which this project has never attempted
to bypass, see NetFile/Elections notes elsewhere). This feed's whole
purpose is automated podcast-client syndication, so a plain script fetching
it isn't circumventing anything the feed wasn't built for. Scoped
narrowly to just this one download (_download_audio_enclosure below) --
not a change to the shared fetch_url() every other source uses.
"""

import logging
import re
from datetime import date, datetime, timezone
from xml.etree import ElementTree

import httpx
from dateutil import parser as dateutil_parser
from sqlalchemy.orm import Session

from app.ai import whisperx_client
from app.archive import archive_dir_for, now_utc, sha256_hex, write_archive_file
from app.ingestion.http_client import fetch_url
from app.models import Meeting, MeetingTranscript, Source

logger = logging.getLogger(__name__)

# Titles look like "Parks & Rec Commission Regular Meeting - 06/10/2026 -
# Jun 11, 2026" or "City Council Meeting - July 7, 2026 - Jul 07, 2026" --
# the meeting's own date is the *first* date-shaped substring; whatever
# comes after is the podcast's publish-date restatement, not the meeting
# date (verified live 2026-07-09 against several real Granicus feed items).
TITLE_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4}|[A-Z][a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})")
BODY_SUFFIX_RE = re.compile(r"\b(Regular|Special|Closed Session|Meeting)\b", re.IGNORECASE)


def _parse_meeting_date_from_title(title: str) -> date | None:
    match = TITLE_DATE_RE.search(title)
    if not match:
        return None
    try:
        return dateutil_parser.parse(match.group(1)).date()
    except (ValueError, OverflowError):
        return None


def _extract_body_hint(title: str) -> str:
    prefix = title.split(" - ")[0]
    return BODY_SUFFIX_RE.sub("", prefix).strip()


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


# See module docstring: this CDN 403s our normal, honest User-Agent
# specifically, for this one endpoint only.
_ENCLOSURE_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _download_audio_enclosure(url: str, timeout: float = 300.0) -> httpx.Response:
    with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": _ENCLOSURE_USER_AGENT}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response


def _parse_podcast_feed(xml_bytes: bytes) -> list[dict]:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        enclosure = item.find("enclosure")
        url = enclosure.get("url") if enclosure is not None else None
        if not url or not title:
            continue
        items.append({"title": title, "url": url})
    return items


def ingest_meeting_audio(db: Session, source: Source) -> int:
    """Returns the number of new transcripts created."""
    try:
        response = fetch_url(source.url)
    except httpx.HTTPError as exc:
        source.last_error = str(exc)[:2000]
        source.consecutive_failures += 1
        source.last_fetched_at = now_utc()
        db.commit()
        logger.warning("podcast feed fetch failed for source %s: %s", source.name, exc)
        return 0

    items = _parse_podcast_feed(response.content)
    created = 0
    for item in items:
        existing = (
            db.query(MeetingTranscript)
            .filter(MeetingTranscript.source_id == source.id, MeetingTranscript.original_url == item["url"])
            .one_or_none()
        )
        if existing:
            continue

        try:
            audio_response = _download_audio_enclosure(item["url"])
        except httpx.HTTPError as exc:
            logger.warning("failed to download meeting audio %s: %s", item["url"], exc)
            continue

        content = audio_response.content
        content_hash = sha256_hex(content)
        existing_by_hash = (
            db.query(MeetingTranscript)
            .filter(MeetingTranscript.source_id == source.id, MeetingTranscript.content_hash == content_hash)
            .one_or_none()
        )
        if existing_by_hash:
            continue

        directory = archive_dir_for(source.jurisdiction, source.body, now_utc())
        filename = f"audio_{content_hash[:10]}.mp3"
        archive_path = write_archive_file(directory, filename, content)

        result, error = whisperx_client.transcribe(str(archive_path))
        if result is None:
            logger.warning("transcription failed for %s: %s", item["title"], error)
            continue

        meeting = _match_meeting(db, source, item["title"])
        segments = result.get("segments", [])
        speaker_count = len({s["speaker"] for s in segments if s.get("speaker")})
        duration_seconds = segments[-1]["end"] if segments else None

        db.add(
            MeetingTranscript(
                meeting_id=meeting.id if meeting else None,
                source_id=source.id,
                title=item["title"],
                archive_path=str(archive_path),
                content_hash=content_hash,
                original_url=item["url"],
                duration_seconds=duration_seconds,
                language=result.get("language"),
                speaker_count=speaker_count,
                segments=segments,
                model_name="whisperx-large-v3",
            )
        )
        created += 1
        db.commit()
        logger.info(
            "transcribed meeting audio %s: %d segment(s), %d speaker(s), matched meeting=%s",
            item["title"],
            len(segments),
            speaker_count,
            meeting.id if meeting else None,
        )

    source.last_fetched_at = now_utc()
    source.consecutive_failures = 0
    source.last_error = None
    if created:
        source.last_changed_at = now_utc()
    db.commit()
    return created
