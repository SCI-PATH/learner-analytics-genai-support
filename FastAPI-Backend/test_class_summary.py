"""Unit tests for additive class-summary / diagnostic helpers (no Postgres)."""

from __future__ import annotations

import unittest

from main import (
    _build_diagnostic_skills,
    _compose_topic_risk_alert,
    _engagement_mastery_gap_payload,
    _hardest_skills_from_matrix,
    _mastery_band_counts_from_matrix,
    _privacy_safe_recent_attempts,
    _top_at_risk_skills,
)


class DiagnosticSkillsTests(unittest.TestCase):
    def test_flags_high_slip_and_high_guess(self) -> None:
        payload = _build_diagnostic_skills(
            [
                {
                    "topic_id": "G7_C1_SLIPPY",
                    "p_l": 0.62,
                    "mastery_category": "intermediate",
                    "p_s": 0.22,
                    "p_g": 0.10,
                },
                {
                    "topic_id": "G7_C1_GUESSY",
                    "p_l": 0.81,
                    "mastery_category": "advanced",
                    "p_s": 0.08,
                    "p_g": 0.31,
                },
                {
                    "topic_id": "G7_C1_STABLE",
                    "p_l": 0.40,
                    "mastery_category": "basic",
                    "p_s": 0.10,
                    "p_g": 0.20,
                },
            ]
        )
        self.assertEqual(payload["count"], 2)
        self.assertEqual([row["topic_id"] for row in payload["high_slip"]], ["G7_C1_SLIPPY"])
        self.assertEqual([row["topic_id"] for row in payload["high_guess"]], ["G7_C1_GUESSY"])
        self.assertEqual(payload["thresholds"]["p_s"], 0.15)
        self.assertEqual(payload["thresholds"]["p_g"], 0.20)


class EngagementMasteryGapTests(unittest.TestCase):
    def test_flags_high_engagement_low_mastery(self) -> None:
        gap = _engagement_mastery_gap_payload(0.82, 0.41)
        self.assertTrue(gap["flagged"])

    def test_does_not_flag_when_mastery_is_ok(self) -> None:
        gap = _engagement_mastery_gap_payload(0.90, 0.55)
        self.assertFalse(gap["flagged"])

    def test_does_not_flag_missing_series(self) -> None:
        self.assertFalse(_engagement_mastery_gap_payload(None, 0.20)["flagged"])
        self.assertFalse(_engagement_mastery_gap_payload(0.90, None)["flagged"])


class RecentAttemptsTests(unittest.TestCase):
    def test_strips_free_text_and_keeps_error_category(self) -> None:
        rows = _privacy_safe_recent_attempts(
            [
                {
                    "topic_id": "G7_C2_FORCE",
                    "is_correct": False,
                    "response_time_s": 12.5,
                    "updated_mastery_probability": 0.33,
                    "distractor_label": "Force is energy",
                    "question_type": "MCQ",
                    "error_category": "CONCEPTUAL_MISCONCEPTION",
                    "detailed_explanation": "Student wrote a private sentence.",
                    "timestamp": "2026-08-22T10:00:00+00:00",
                }
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["error_category"], "CONCEPTUAL_MISCONCEPTION")
        self.assertNotIn("detailed_explanation", rows[0])
        self.assertFalse(rows[0]["is_correct"])


class ClassAggregationTests(unittest.TestCase):
    def test_mastery_band_counts(self) -> None:
        matrix = {
            "s1": {"t1": 0.82, "t2": 0.40},
            "s2": {"t1": 0.60, "t2": 0.49},
        }
        bands = _mastery_band_counts_from_matrix(matrix, ["s1", "s2"], ["t1", "t2"])
        self.assertEqual(bands["mastered"], 1)
        self.assertEqual(bands["learning"], 1)
        self.assertEqual(bands["at_risk"], 2)
        self.assertEqual(bands["total"], 4)

    def test_hardest_skills_rank_by_at_risk_share(self) -> None:
        matrix = {
            "s1": {"easy": 0.90, "hard": 0.20},
            "s2": {"easy": 0.85, "hard": 0.30},
        }
        ranked = _hardest_skills_from_matrix(matrix, ["s1", "s2"], ["easy", "hard"], top_n=2)
        self.assertEqual(ranked[0]["topic_id"], "hard")
        self.assertEqual(ranked[0]["at_risk_count"], 2)

    def test_top_at_risk_skills_from_alerts(self) -> None:
        ranked = _top_at_risk_skills(
            [
                {"topic_id": "tA", "risk_score": 80},
                {"topic_id": "tA", "risk_score": 60},
                {"topic_id": "tB", "risk_score": 90},
            ],
            top_n=2,
        )
        self.assertEqual(ranked[0]["topic_id"], "tA")
        self.assertEqual(ranked[0]["alert_count"], 2)
        self.assertEqual(ranked[0]["avg_risk_score"], 70.0)


class RiskScoreBandTests(unittest.TestCase):
    def test_critical_low_mastery_is_immediate_support(self) -> None:
        alert = _compose_topic_risk_alert(
            student_id="g8_demo_nimal",
            topic_id="G8_C11_PHO_PROCESS",
            mastery=0.12,
            low_mastery=True,
            neg_velocity=True,
            weak_recent_perf=True,
            recent_signal_tail=[0.22, 0.16, 0.11],
            recent_performance_avg=0.16,
        )
        self.assertIsNotNone(alert)
        self.assertGreaterEqual(alert["risk_score"], 80)

    def test_low_and_weak_without_critical_is_needs_attention(self) -> None:
        alert = _compose_topic_risk_alert(
            student_id="g8_demo_dilani",
            topic_id="G8_C10_ELE_CIRCUITS",
            mastery=0.37,
            low_mastery=True,
            neg_velocity=False,
            weak_recent_perf=True,
            recent_signal_tail=[0.35, 0.40, 0.33],
            recent_performance_avg=0.36,
        )
        self.assertIsNotNone(alert)
        self.assertGreaterEqual(alert["risk_score"], 60)
        self.assertLess(alert["risk_score"], 80)

    def test_trend_without_low_mastery_is_watchlist(self) -> None:
        alert = _compose_topic_risk_alert(
            student_id="g8_demo_kavindu",
            topic_id="G8_C4_MAT_PARTICLE",
            mastery=0.62,
            low_mastery=False,
            neg_velocity=True,
            weak_recent_perf=True,
            recent_signal_tail=[0.32, 0.25, 0.18],
            recent_performance_avg=0.32,
        )
        self.assertIsNotNone(alert)
        self.assertEqual(alert["risk_score"], 55)


if __name__ == "__main__":
    unittest.main()
