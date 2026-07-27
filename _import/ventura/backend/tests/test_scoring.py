"""Tests for alert-level computation (prd.md 9.12, 12) -- pure logic, no I/O,
but the branching (high_impact / imminent / action_window) is exactly the
kind of thing that's easy to get subtly wrong and hard to notice, since a
wrong level just means an alert quietly shows up in the wrong bucket rather
than crashing anything.
"""

from datetime import timedelta

from app.archive import now_utc
from app.scoring import alert_level_for

TODAY = now_utc().date()


def days_from_now(n: int):
    return TODAY + timedelta(days=n)


class TestLevel4HighImpactImminent:
    def test_high_importance_and_meeting_within_a_week_is_level_4(self):
        assert alert_level_for(8, 1, 0, days_from_now(3)) == 4

    def test_high_transparency_risk_and_meeting_within_a_week_is_level_4(self):
        assert alert_level_for(0, 1, 8, days_from_now(3)) == 4

    def test_high_importance_and_urgency_8_plus_is_level_4_even_without_a_meeting_date(self):
        assert alert_level_for(8, 8, 0, None) == 4

    def test_meeting_today_counts_as_imminent(self):
        assert alert_level_for(9, 0, 0, days_from_now(0)) == 4

    def test_meeting_exactly_7_days_out_counts_as_imminent(self):
        assert alert_level_for(9, 0, 0, days_from_now(7)) == 4

    def test_meeting_8_days_out_does_not_count_as_imminent(self):
        # 8 days out with low urgency and no meeting-independent urgency
        # boost should NOT reach level 4.
        assert alert_level_for(9, 1, 0, days_from_now(8)) != 4

    def test_past_meeting_date_does_not_count_as_imminent(self):
        assert alert_level_for(9, 1, 0, days_from_now(-1)) != 4


class TestLevel3ActionWindow:
    def test_urgency_6_alone_is_level_3_without_high_impact(self):
        assert alert_level_for(1, 6, 1, None) == 3

    def test_imminent_meeting_alone_is_level_3_without_high_impact(self):
        assert alert_level_for(1, 1, 1, days_from_now(2)) == 3

    def test_high_impact_but_not_imminent_and_urgency_under_8_is_not_level_4(self):
        # High importance scheduled far out with low urgency shouldn't
        # spuriously escalate to 4 -- this is the asymmetric case where
        # high_impact alone isn't sufficient without imminence or urgency>=8.
        assert alert_level_for(9, 1, 0, days_from_now(30)) != 4

    def test_high_impact_with_moderate_urgency_and_no_imminence_lands_at_3(self):
        # urgency=6 triggers action_window even though it's below the 8
        # needed to combine with high_impact for a level 4.
        assert alert_level_for(9, 6, 0, days_from_now(30)) == 3


class TestLevel2Relevant:
    def test_moderate_importance_with_no_urgency_or_imminence_is_level_2(self):
        assert alert_level_for(3, 1, 0, None) == 2

    def test_moderate_transparency_risk_alone_is_level_2(self):
        assert alert_level_for(0, 1, 3, None) == 2

    def test_high_impact_scheduled_far_out_with_low_urgency_lands_at_2_not_3(self):
        # Traced explicitly: high_impact=True, imminent=False, urgency=1 (<6)
        # so action_window is also False -- falls through to the >=3 check.
        assert alert_level_for(9, 1, 0, days_from_now(30)) == 2


class TestLevel1Captured:
    def test_everything_low_is_level_1(self):
        assert alert_level_for(1, 1, 1, None) == 1

    def test_all_zero_is_level_1(self):
        assert alert_level_for(0, 0, 0, None) == 1

    def test_just_below_relevant_threshold_is_level_1(self):
        assert alert_level_for(2, 1, 2, None) == 1
