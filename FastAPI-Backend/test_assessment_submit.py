import unittest

from pydantic import ValidationError

from main import AssessmentSubmitRequest, _canonicalize_question_type, _normalize_assessment_attempt


class QuestionTypeCanonicalizeTests(unittest.TestCase):
    def test_canonical_values(self) -> None:
        for value in ("MCQ", "ShortAnswer", "MultiBlank", "TrueFalse"):
            self.assertEqual(_canonicalize_question_type(value), value)

    def test_short_answer_alias(self) -> None:
        self.assertEqual(_canonicalize_question_type("SHORT_ANSWER"), "ShortAnswer")

    def test_invalid_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            _canonicalize_question_type("Essay")


class AssessmentSubmitRequestTests(unittest.TestCase):
    def test_short_answer_alias_on_model(self) -> None:
        req = AssessmentSubmitRequest(
            user_id="student_001",
            topic_id="G8_C11_PHO_PROCESS",
            is_correct=False,
            question_type="SHORT_ANSWER",
            similarity_score=0.45,
            error_category="MISSING_KEYWORDS",
            detailed_explanation="The answer omitted chlorophyll and light energy.",
        )
        self.assertEqual(req.question_type, "ShortAnswer")
        self.assertEqual(req.error_category, "MISSING_KEYWORDS")

    def test_multiblank_payload(self) -> None:
        req = AssessmentSubmitRequest(
            user_id="student_001",
            topic_id="G7_C5_ACI_IDENTIF",
            is_correct=False,
            question_type="MultiBlank",
            similarity_score=0.5,
            error_category="PARTIAL_MASTERY",
            missed_blanks={"1": "base"},
        )
        self.assertEqual(req.question_type, "MultiBlank")
        self.assertEqual(req.missed_blanks, {"1": "base"})

    def test_truefalse_payload(self) -> None:
        req = AssessmentSubmitRequest(
            user_id="student_001",
            topic_id="G6_C7_MAG_POLES",
            is_correct=False,
            question_type="TrueFalse",
            detailed_explanation="The statement is true because opposite poles attract.",
        )
        self.assertEqual(req.question_type, "TrueFalse")

    def test_null_enrichment_fields_accepted(self) -> None:
        req = AssessmentSubmitRequest(
            user_id="student_001",
            topic_id="G6_C7_MAG_POLES",
            is_correct=True,
            question_type="MCQ",
            similarity_score=None,
            distractor_tag=None,
            error_category=None,
            detailed_explanation=None,
            missed_blanks=None,
        )
        self.assertEqual(req.question_type, "MCQ")
        self.assertIsNone(req.error_category)

    def test_unknown_question_type_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AssessmentSubmitRequest(
                user_id="student_001",
                topic_id="G6_C7_MAG_POLES",
                is_correct=True,
                question_type="Essay",
            )

    def test_attempt_record_keeps_enrichment_fields(self) -> None:
        record = _normalize_assessment_attempt(
            {
                "user_id": "student_001",
                "topic_id": "G7_C5_ACI_IDENTIF",
                "is_correct": False,
                "question_type": "MultiBlank",
                "error_category": "PARTIAL_MASTERY",
                "detailed_explanation": None,
                "missed_blanks": {"1": "base"},
                "similarity_score": 0.5,
            }
        )
        self.assertEqual(record["error_category"], "PARTIAL_MASTERY")
        self.assertEqual(record["missed_blanks"], {"1": "base"})
        self.assertEqual(record["similarity_score"], 0.5)
        self.assertNotIn("detailed_explanation", record)


class ScoreReasoningMappingTests(unittest.TestCase):
    def test_plain_explanation(self) -> None:
        from postgres_store import score_reasoning_from_attempt

        text = score_reasoning_from_attempt(
            {"detailed_explanation": "Opposite poles attract."}
        )
        self.assertEqual(text, "Opposite poles attract.")

    def test_explanation_does_not_pack_other_fields(self) -> None:
        from postgres_store import score_reasoning_from_attempt

        text = score_reasoning_from_attempt(
            {
                "detailed_explanation": "Opposite poles attract.",
                "error_category": "PARTIAL_MASTERY",
                "missed_blanks": {"1": "base"},
            }
        )
        self.assertEqual(text, "Opposite poles attract.")


class PostgresParamMappingTests(unittest.TestCase):
    def test_literature_default_row_shape(self) -> None:
        from postgres_store import fetch_skill_params, postgres_configured

        if not postgres_configured():
            self.skipTest("DATABASE_URL not set")
        params = fetch_skill_params("G6_C7_MAG_POLES")
        if params is None:
            self.skipTest("bkt_skill_params row not found")
        self.assertAlmostEqual(params["prior"], 0.25)
        self.assertAlmostEqual(params["learn"], 0.15)
        self.assertAlmostEqual(params["guess"], 0.2)
        self.assertAlmostEqual(params["slip"], 0.1)
        self.assertAlmostEqual(params["forget"], 0.0)


if __name__ == "__main__":
    unittest.main()
