"""Tests for Granicus podcast-feed audio ingestion + transcription. Structurally
different from every other ingestion module under test: no document parsing,
just RSS-feed parsing, a UA-specific download step (see meeting_audio.py's
module docstring for why), and a best-effort date/body match back to a
Meeting row. The transcription service itself (whisperx_client.transcribe) is
mocked -- these tests aren't re-verifying WhisperX, just this module's
ingestion/dedup/matching logic around it.
"""

from datetime import datetime, timezone

import httpx

import app.ingestion.meeting_audio as meeting_audio_module
from app.ingestion.meeting_audio import (
    _download_audio_enclosure,
    _extract_body_hint,
    _match_meeting,
    _parse_meeting_date_from_title,
    _parse_podcast_feed,
    ingest_meeting_audio,
)
from app.models import MeetingTranscript

from .conftest import make_meeting, make_source

PODCAST_FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<item>
<title>City Council Meeting - July 7, 2026 - Jul 07, 2026</title>
<enclosure url="https://archive-video.granicus.com/cityofventura/cityofventura_abc123.mp3" type="audio/mpeg"/>
</item>
<item>
<title>Parks &amp; Rec Commission Regular Meeting - 06/10/2026 - Jun 11, 2026</title>
<enclosure url="https://archive-video.granicus.com/cityofventura/cityofventura_def456.mp3" type="audio/mpeg"/>
</item>
<item>
<title>No enclosure here</title>
</item>
</channel>
</rss>
"""

FAKE_TRANSCRIPTION_RESULT = {
    "language": "en",
    "segments": [
        {"start": 0.0, "end": 5.0, "text": "Good evening.", "speaker": "SPEAKER_00"},
        {"start": 5.0, "end": 10.0, "text": "Motion carries.", "speaker": "SPEAKER_01"},
    ],
}


class FakeFetchResponse:
    def __init__(self, content):
        self.content = content


class TestParsePodcastFeed:
    def test_parses_items_with_title_and_enclosure(self):
        items = _parse_podcast_feed(PODCAST_FEED_XML)

        assert len(items) == 2
        assert items[0]["title"] == "City Council Meeting - July 7, 2026 - Jul 07, 2026"
        assert items[0]["url"] == "https://archive-video.granicus.com/cityofventura/cityofventura_abc123.mp3"

    def test_items_missing_title_or_enclosure_are_skipped(self):
        items = _parse_podcast_feed(PODCAST_FEED_XML)

        assert all(item["title"] != "No enclosure here" for item in items)

    def test_malformed_xml_returns_empty_list(self):
        assert _parse_podcast_feed(b"not valid xml at all") == []


class TestParseMeetingDateFromTitle:
    def test_parses_slash_date(self):
        assert _parse_meeting_date_from_title("Parks & Rec Commission Regular Meeting - 06/10/2026 - Jun 11, 2026").isoformat() == "2026-06-10"

    def test_parses_month_name_date(self):
        assert _parse_meeting_date_from_title("City Council Meeting - July 7, 2026 - Jul 07, 2026").isoformat() == "2026-07-07"

    def test_uses_first_date_not_publish_date_restatement(self):
        # The trailing "Jun 11, 2026" is the podcast publish-date restatement,
        # not the meeting's own date -- see module docstring.
        result = _parse_meeting_date_from_title("Parks & Rec Commission Regular Meeting - 06/10/2026 - Jun 11, 2026")
        assert result.isoformat() != "2026-06-11"

    def test_no_date_shaped_text_returns_none(self):
        assert _parse_meeting_date_from_title("Untitled Recording") is None

    def test_date_shaped_but_invalid_date_returns_none(self):
        # month=13 is date-shaped enough to match TITLE_DATE_RE but not a
        # real calendar date -- dateutil raises ParserError (a ValueError
        # subclass), which should be swallowed rather than propagated.
        assert _parse_meeting_date_from_title("Some Meeting - 13/45/2026") is None


class TestExtractBodyHint:
    def test_strips_meeting_type_suffix(self):
        assert _extract_body_hint("Parks & Rec Commission Regular Meeting - 06/10/2026") == "Parks & Rec Commission"

    def test_takes_only_the_part_before_first_dash(self):
        assert _extract_body_hint("City Council Meeting - July 7, 2026 - Jul 07, 2026") == "City Council"


class TestMatchMeeting:
    def test_matches_single_meeting_on_same_day(self, db):
        meeting = make_meeting(db, start_time=datetime(2026, 7, 7, 18, 0, tzinfo=timezone.utc))
        source = make_source(db)

        result = _match_meeting(db, source, "City Council Meeting - July 7, 2026 - Jul 07, 2026")

        assert result.id == meeting.id

    def test_no_meeting_on_that_day_returns_none(self, db):
        source = make_source(db)

        result = _match_meeting(db, source, "City Council Meeting - July 7, 2026 - Jul 07, 2026")

        assert result is None

    def test_title_with_no_parseable_date_returns_none(self, db):
        source = make_source(db)

        assert _match_meeting(db, source, "Untitled Recording") is None

    def test_multiple_same_day_meetings_disambiguated_by_body(self, db):
        source = make_source(db)
        make_meeting(db, body="City Council", start_time=datetime(2026, 7, 7, 14, 0, tzinfo=timezone.utc))
        parks_rec = make_meeting(db, body="Parks & Rec Commission", start_time=datetime(2026, 7, 7, 18, 0, tzinfo=timezone.utc))

        result = _match_meeting(db, source, "Parks & Rec Commission Regular Meeting - 07/07/2026 - Jul 08, 2026")

        assert result.id == parks_rec.id

    def test_multiple_same_day_meetings_no_body_match_falls_back_to_first(self, db):
        source = make_source(db)
        first = make_meeting(db, body="City Council", start_time=datetime(2026, 7, 7, 14, 0, tzinfo=timezone.utc))
        make_meeting(db, body="Planning Commission", start_time=datetime(2026, 7, 7, 18, 0, tzinfo=timezone.utc))

        result = _match_meeting(db, source, "Some Other Body Regular Meeting - 07/07/2026")

        assert result.id == first.id

    def test_only_matches_meetings_in_the_same_jurisdiction(self, db):
        make_meeting(db, jurisdiction="Ventura County", start_time=datetime(2026, 7, 7, 18, 0, tzinfo=timezone.utc))
        source = make_source(db, jurisdiction="City of Ventura")

        result = _match_meeting(db, source, "City Council Meeting - July 7, 2026")

        assert result is None


class FakeHttpxResponse:
    def __init__(self, content=b"mp3 bytes"):
        self.content = content

    def raise_for_status(self):
        pass


class FakeHttpxClient:
    def __init__(self, response, **kwargs):
        self._response = response
        self.received_headers = kwargs.get("headers")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        return self._response


class TestDownloadAudioEnclosure:
    def test_sends_browser_like_user_agent_not_the_project_default(self, monkeypatch):
        # This CDN 403s the project's honest, self-identifying UA -- see
        # module docstring. Pin down that this function deliberately uses a
        # different, generic UA rather than the shared settings.http_user_agent.
        response = FakeHttpxResponse(content=b"real mp3 bytes")
        captured_clients = []

        def fake_client(**kwargs):
            client = FakeHttpxClient(response, **kwargs)
            captured_clients.append(client)
            return client

        monkeypatch.setattr(meeting_audio_module.httpx, "Client", fake_client)

        result = _download_audio_enclosure("https://archive-video.granicus.com/example.mp3")

        assert result.content == b"real mp3 bytes"
        assert captured_clients[0].received_headers["User-Agent"] == meeting_audio_module._ENCLOSURE_USER_AGENT


class TestIngestMeetingAudio:
    def _install(self, monkeypatch, feed_xml=PODCAST_FEED_XML, download_bytes=None, transcribe_result=(FAKE_TRANSCRIPTION_RESULT, None)):
        monkeypatch.setattr(meeting_audio_module, "fetch_url", lambda url: FakeFetchResponse(feed_xml))
        if download_bytes is None:
            # Distinct content per URL by default, so multi-item feeds don't
            # collide on content_hash dedup.
            download_fn = lambda url, timeout=300.0: FakeFetchResponse(f"fake mp3 bytes for {url}".encode())
        else:
            download_fn = lambda url, timeout=300.0: FakeFetchResponse(download_bytes)
        monkeypatch.setattr(meeting_audio_module, "_download_audio_enclosure", download_fn)
        monkeypatch.setattr(meeting_audio_module.whisperx_client, "transcribe", lambda path: transcribe_result)

    def test_creates_transcripts_for_each_new_feed_item(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")
        self._install(monkeypatch)

        created = ingest_meeting_audio(db, source)

        assert created == 2
        assert db.query(MeetingTranscript).filter_by(source_id=source.id).count() == 2

    def test_transcript_fields_are_populated_from_transcription_result(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")
        self._install(monkeypatch, feed_xml=PODCAST_FEED_XML)

        ingest_meeting_audio(db, source)

        transcript = db.query(MeetingTranscript).filter_by(source_id=source.id).first()
        assert transcript.language == "en"
        assert transcript.speaker_count == 2
        assert transcript.duration_seconds == 10.0
        assert len(transcript.segments) == 2

    def test_rerunning_dedupes_by_original_url(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")
        self._install(monkeypatch)

        first = ingest_meeting_audio(db, source)
        second = ingest_meeting_audio(db, source)

        assert first == 2
        assert second == 0
        assert db.query(MeetingTranscript).filter_by(source_id=source.id).count() == 2

    def test_transcript_linked_to_matching_meeting_when_found(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")
        meeting = make_meeting(db, body="City Council", start_time=datetime(2026, 7, 7, 18, 0, tzinfo=timezone.utc))
        self._install(monkeypatch)

        ingest_meeting_audio(db, source)

        transcript = (
            db.query(MeetingTranscript)
            .filter_by(source_id=source.id, title="City Council Meeting - July 7, 2026 - Jul 07, 2026")
            .one()
        )
        assert transcript.meeting_id == meeting.id

    def test_transcript_left_unlinked_when_no_meeting_matches(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")
        self._install(monkeypatch)

        ingest_meeting_audio(db, source)

        transcripts = db.query(MeetingTranscript).filter_by(source_id=source.id).all()
        assert all(t.meeting_id is None for t in transcripts)

    def test_feed_fetch_failure_is_recorded_and_does_not_crash(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")

        def boom(url):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(meeting_audio_module, "fetch_url", boom)

        created = ingest_meeting_audio(db, source)

        assert created == 0
        assert source.consecutive_failures == 1
        assert source.last_error is not None

    def test_audio_download_failure_for_one_item_does_not_block_the_rest(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")
        monkeypatch.setattr(meeting_audio_module, "fetch_url", lambda url: FakeFetchResponse(PODCAST_FEED_XML))
        monkeypatch.setattr(meeting_audio_module.whisperx_client, "transcribe", lambda path: (FAKE_TRANSCRIPTION_RESULT, None))

        calls = []

        def flaky_download(url, timeout=300.0):
            calls.append(url)
            if len(calls) == 1:
                raise httpx.HTTPStatusError("403 forbidden", request=None, response=None)
            return FakeFetchResponse(b"fake mp3 bytes")

        monkeypatch.setattr(meeting_audio_module, "_download_audio_enclosure", flaky_download)

        created = ingest_meeting_audio(db, source)

        assert created == 1

    def test_transcription_failure_for_one_item_does_not_block_the_rest(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")
        monkeypatch.setattr(meeting_audio_module, "fetch_url", lambda url: FakeFetchResponse(PODCAST_FEED_XML))
        monkeypatch.setattr(
            meeting_audio_module, "_download_audio_enclosure", lambda url, timeout=300.0: FakeFetchResponse(b"fake mp3 bytes")
        )

        calls = []

        def flaky_transcribe(path):
            calls.append(path)
            if len(calls) == 1:
                return None, "whisperx request failed: connection refused"
            return FAKE_TRANSCRIPTION_RESULT, None

        monkeypatch.setattr(meeting_audio_module.whisperx_client, "transcribe", flaky_transcribe)

        created = ingest_meeting_audio(db, source)

        assert created == 1

    def test_dedupes_by_content_hash_even_with_different_urls(self, db, archive_root, monkeypatch):
        # Same underlying audio bytes served from two different enclosure
        # URLs (e.g. a re-published feed entry) shouldn't create two rows.
        source = make_source(db, fetch_method="granicus_podcast_rss")
        original_feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>City Council Meeting - July 7, 2026 - Jul 07, 2026</title>
<enclosure url="https://archive-video.granicus.com/cityofventura/cityofventura_original.mp3" type="audio/mpeg"/>
</item></channel></rss>
"""
        self._install(monkeypatch, feed_xml=original_feed, download_bytes=b"identical audio bytes")

        first_created = ingest_meeting_audio(db, source)
        assert first_created == 1

        duplicate_feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>City Council Meeting - July 7, 2026 - Jul 07, 2026 (re-upload)</title>
<enclosure url="https://archive-video.granicus.com/cityofventura/cityofventura_reupload.mp3" type="audio/mpeg"/>
</item></channel></rss>
"""
        self._install(monkeypatch, feed_xml=duplicate_feed, download_bytes=b"identical audio bytes")

        second_created = ingest_meeting_audio(db, source)

        assert second_created == 0

    def test_updates_source_fetch_bookkeeping_on_success(self, db, archive_root, monkeypatch):
        source = make_source(db, fetch_method="granicus_podcast_rss")
        self._install(monkeypatch)

        ingest_meeting_audio(db, source)

        assert source.last_fetched_at is not None
        assert source.consecutive_failures == 0
        assert source.last_error is None
        assert source.last_changed_at is not None
