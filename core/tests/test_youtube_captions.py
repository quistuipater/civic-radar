"""Tests for MVC YouTube-channel caption ingestion. Structurally similar to
test_meeting_audio.py: the yt-dlp-touching functions are monkeypatched, these
tests exercise this module's own listing-filter/date-match/VTT-parse/dedup
logic.
"""

from datetime import datetime, timezone

import app.ingestion.youtube_captions as youtube_captions_module
from app.ingestion.youtube_captions import (
    _extract_body_hint,
    _is_governance_meeting_title,
    _match_meeting,
    _parse_meeting_date_from_title,
    _parse_vtt,
)
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


class TestIsGovernanceMeetingTitle:
    def test_water_alliance_meeting_is_governance(self):
        assert _is_governance_meeting_title("Martha's Vineyard Water Alliance Meeting 4/17/25") is True

    def test_land_use_planning_committee_is_governance(self):
        assert _is_governance_meeting_title("MVC Land Use Planning Committee Meeting 6/12/2023") is True

    def test_joint_affordable_housing_group_is_governance(self):
        assert _is_governance_meeting_title("Joint Affordable Housing Group 1-7-2026") is True

    def test_public_forum_is_governance(self):
        assert _is_governance_meeting_title("Road Safety Action Plan Public Forum 2 5 25") is True

    def test_gis_tutorial_is_not_governance(self):
        assert _is_governance_meeting_title("GIS How-to Upload Coordinate Spreadsheet to ArcGIS OnLine") is False

    def test_oral_history_interview_is_not_governance(self):
        assert _is_governance_meeting_title("Donald Widdiss 9-24-24") is False

    def test_photo_tour_is_not_governance(self):
        assert _is_governance_meeting_title("Menemsha Pond Photo Tour") is False

    def test_verizon_tower_video_is_not_governance(self):
        assert _is_governance_meeting_title("Tisbury MA Verizon Tower 144ft") is False


class TestParseMeetingDateFromTitleYoutube:
    def test_parses_dash_separated_two_digit_year(self):
        assert _parse_meeting_date_from_title("Joint Affordable Housing Group 10-8-25").isoformat() == "2025-10-08"

    def test_parses_slash_separated_two_digit_year(self):
        assert _parse_meeting_date_from_title("Martha's Vineyard Water Alliance Meeting 4/17/25").isoformat() == "2025-04-17"

    def test_parses_full_four_digit_year(self):
        assert _parse_meeting_date_from_title("MVC Land Use Planning Committee Meeting 6/12/2023").isoformat() == "2023-06-12"

    def test_parses_month_name_date(self):
        assert _parse_meeting_date_from_title("Manuel Correllus State Task Force - June 10, 2025").isoformat() == "2025-06-10"

    def test_no_date_returns_none(self):
        assert _parse_meeting_date_from_title("MVC Climate Action Task Force - Wildfire Risk & Mitigation") is None


class TestExtractBodyHintYoutube:
    def test_takes_text_before_the_date(self):
        assert _extract_body_hint("Martha's Vineyard Water Alliance Meeting 4/17/25") == "Martha's Vineyard Water Alliance"

    def test_strips_trailing_dash(self):
        assert _extract_body_hint("Manuel Correllus State Task Force - June 10, 2025") == "Manuel Correllus State Task Force"


class TestMatchMeetingYoutube:
    def test_matches_meeting_on_same_day_and_jurisdiction(self, db):
        source = make_source(db, jurisdiction="Martha's Vineyard Commission")
        meeting = make_meeting(
            db,
            jurisdiction="Martha's Vineyard Commission",
            body="Land Use Planning Committee",
            start_time=datetime(2023, 6, 12, 18, 0, tzinfo=timezone.utc),
        )

        result = _match_meeting(db, source, "MVC Land Use Planning Committee Meeting 6/12/2023")

        assert result.id == meeting.id

    def test_no_meeting_that_day_returns_none(self, db):
        source = make_source(db, jurisdiction="Martha's Vineyard Commission")

        result = _match_meeting(db, source, "MVC Land Use Planning Committee Meeting 6/12/2023")

        assert result is None
