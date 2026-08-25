import unittest

from pydantic import ValidationError

from curriculum_topics import (
    chapter_id_for_topic,
    normalize_chapter_id,
    resolve_chapter_scope,
    topic_ids_for_chapter,
)
from main import AssessmentSubmitRequest, QuizBktSnapshotRequest


class ChapterIdHelperTests(unittest.TestCase):
    def test_canonical_chapter_from_topic(self) -> None:
        self.assertEqual(chapter_id_for_topic("G6_C8_ELE_CIRCUITS"), "G6_C8")
        self.assertEqual(chapter_id_for_topic("G6_C8_ELE_CONDINS"), "G6_C8")

    def test_legacy_topic_id_maps_to_chapter(self) -> None:
        self.assertEqual(chapter_id_for_topic("G6_S8_ELE_CONDINS"), "G6_C8")

    def test_normalize_accepts_loose_chapter_keys(self) -> None:
        self.assertEqual(normalize_chapter_id("g6_c8"), "G6_C8")
        self.assertEqual(normalize_chapter_id("G6-C8"), "G6_C8")
        self.assertEqual(normalize_chapter_id("G6_C08"), "G6_C8")
        self.assertEqual(normalize_chapter_id("G6_C8_ELE_CIRCUITS"), "G6_C8")

    def test_chapter_has_two_topic_ids(self) -> None:
        topics = topic_ids_for_chapter("G6_C8")
        self.assertEqual(topics, ["G6_C8_ELE_CIRCUITS", "G6_C8_ELE_CONDINS"])

    def test_resolve_scope_dedupes_and_flags_unknown(self) -> None:
        scope = resolve_chapter_scope(["G6_C8", "g6_c8", "G6_C99", "not-a-chapter"])
        self.assertEqual(scope["chapter_ids"], ["G6_C8"])
        self.assertEqual(scope["topic_ids"], ["G6_C8_ELE_CIRCUITS", "G6_C8_ELE_CONDINS"])
        self.assertEqual(scope["unknown_chapter_ids"], ["G6_C99", "not-a-chapter"])
        self.assertEqual(
            scope["topics_by_chapter"]["G6_C8"],
            ["G6_C8_ELE_CIRCUITS", "G6_C8_ELE_CONDINS"],
        )

    def test_multi_chapter_custom_exam_scope(self) -> None:
        scope = resolve_chapter_scope(["G6_C8", "G6_C7"])
        self.assertEqual(scope["chapter_ids"], ["G6_C8", "G6_C7"])
        self.assertEqual(
            scope["topic_ids"],
            [
                "G6_C8_ELE_CIRCUITS",
                "G6_C8_ELE_CONDINS",
                "G6_C7_MAG_POLES",
                "G6_C7_MAG_FORCES",
            ],
        )


class QuizBktSnapshotRequestTests(unittest.TestCase):
    def test_requires_at_least_one_chapter(self) -> None:
        with self.assertRaises(ValidationError):
            QuizBktSnapshotRequest(user_id="student_001", chapter_ids=[])

    def test_accepts_post_lesson_and_custom_exam(self) -> None:
        one = QuizBktSnapshotRequest(user_id="student_001", chapter_ids=["G6_C8"])
        many = QuizBktSnapshotRequest(
            user_id="student_001", chapter_ids=["G6_C8", "G6_C7"]
        )
        self.assertEqual(one.chapter_ids, ["G6_C8"])
        self.assertEqual(many.chapter_ids, ["G6_C8", "G6_C7"])


class AssessmentSubmitChapterIdsTests(unittest.TestCase):
    def test_chapter_ids_optional_for_backward_compat(self) -> None:
        req = AssessmentSubmitRequest(
            user_id="student_001",
            topic_id="G6_C8_ELE_CIRCUITS",
            is_correct=True,
            question_type="MCQ",
        )
        self.assertIsNone(req.chapter_ids)

    def test_chapter_ids_accepted_for_custom_exam(self) -> None:
        req = AssessmentSubmitRequest(
            user_id="student_001",
            topic_id="G6_C8_ELE_CIRCUITS",
            is_correct=True,
            question_type="MCQ",
            chapter_ids=["G6_C8", "G6_C7"],
        )
        self.assertEqual(req.chapter_ids, ["G6_C8", "G6_C7"])


if __name__ == "__main__":
    unittest.main()
