"""Tests for MVC YouTube-channel caption ingestion. Structurally similar to
test_meeting_audio.py: the yt-dlp-touching functions are monkeypatched, these
tests exercise this module's own listing-filter/date-match/VTT-parse/dedup
logic.
"""

from datetime import datetime, timezone

import app.ingestion.youtube_captions as youtube_captions_module
from app.ingestion.youtube_captions import _parse_vtt
from app.models import MeetingTranscript

from .conftest import make_meeting, make_source

ROLLING_VTT = (
    "WEBVTT\n"
    "Kind: captions\n"
    "Language: en\n"
    "\n"
    "00:00:03.560 --> 00:00:05.510 align:start position:0%\n"
    " \n"
    "Okay,<00:00:04.160><c> so</c><00:00:04.280><c> we're</c><00:00:04.400><c> good</c><00:00:04.560><c> to</c><00:00:04.640><c> go.</c>\n"
    "\n"
    "00:00:05.510 --> 00:00:05.520 align:start position:0%\n"
    "Okay, so we're good to go.\n"
    " \n"
    "\n"
    "00:00:05.520 --> 00:00:09.430 align:start position:0%\n"
    "Okay, so we're good to go.\n"
    "Um,<00:00:05.920><c> Andrew</c><00:00:06.200><c> Karlinsky</c><00:00:07.080><c> is</c><00:00:07.680><c> here.</c>\n"
    "\n"
    "00:00:09.430 --> 00:00:09.440 align:start position:0%\n"
    "Um, Andrew Karlinsky is here.\n"
)


class TestParseVtt:
    def test_merges_rolling_caption_cues_into_one_segment_per_sentence(self):
        segments = _parse_vtt(ROLLING_VTT)

        assert len(segments) == 2
        assert segments[0]["text"] == "Okay, so we're good to go."
        assert segments[0]["start"] == 3.560
        assert segments[0]["end"] == 5.520
        assert segments[1]["text"] == "Um, Andrew Karlinsky is here."
        assert segments[1]["start"] == 5.520
        assert segments[1]["end"] == 9.440

    def test_segments_carry_a_null_speaker_field(self):
        segments = _parse_vtt(ROLLING_VTT)

        assert all(s["speaker"] is None for s in segments)

    def test_empty_vtt_returns_empty_list(self):
        assert _parse_vtt("WEBVTT\n") == []

    def test_strips_inline_c_tags(self):
        segments = _parse_vtt(ROLLING_VTT)

        assert "<c>" not in segments[0]["text"]
        assert "00:00:04.160" not in segments[0]["text"]
