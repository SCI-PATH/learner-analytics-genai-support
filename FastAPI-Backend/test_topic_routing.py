import unittest

import socratic_tutor


class TopicRoutingTests(unittest.TestCase):
    user_id = "topic-routing-test-user"

    def setUp(self) -> None:
        socratic_tutor._last_resolved_topic_by_user.pop(self.user_id, None)

    def tearDown(self) -> None:
        socratic_tutor._last_resolved_topic_by_user.pop(self.user_id, None)

    def test_short_follow_up_keeps_previous_topic(self) -> None:
        socratic_tutor._last_resolved_topic_by_user[self.user_id] = (
            "G8_C11_PHO_PROCESS"
        )
        topic, routing = socratic_tutor._resolve_topic_for_turn(
            self.user_id,
            "Rubber.",
            None,
            [{"role": "assistant", "content": "What material would you choose?"}],
        )

        self.assertEqual(topic, "G8_C11_PHO_PROCESS")
        self.assertEqual(routing, "continued")

    def test_clear_new_question_switches_topic(self) -> None:
        socratic_tutor._last_resolved_topic_by_user[self.user_id] = (
            "G6_C8_ELE_CONDINS"
        )
        topic, routing = socratic_tutor._resolve_topic_for_turn(
            self.user_id,
            "What is photosynthesis?",
            None,
            [{"role": "assistant", "content": "Which material conducts electricity?"}],
        )

        self.assertEqual(topic, "G8_C11_PHO_PROCESS")
        self.assertEqual(routing, "switched")

    def test_explicit_topic_is_authoritative(self) -> None:
        socratic_tutor._last_resolved_topic_by_user[self.user_id] = (
            "G8_C11_PHO_PROCESS"
        )
        topic, routing = socratic_tutor._resolve_topic_for_turn(
            self.user_id,
            "Rubber.",
            "G6_C8_ELE_CONDINS",
            [{"role": "assistant", "content": "What happens next?"}],
        )

        self.assertEqual(topic, "G6_C8_ELE_CONDINS")
        self.assertEqual(routing, "explicit")

    def test_empty_history_starts_fresh_inference(self) -> None:
        socratic_tutor._last_resolved_topic_by_user[self.user_id] = (
            "G6_C8_ELE_CONDINS"
        )
        topic, routing = socratic_tutor._resolve_topic_for_turn(
            self.user_id,
            "What is photosynthesis?",
            None,
            [],
        )

        self.assertEqual(topic, "G8_C11_PHO_PROCESS")
        self.assertEqual(routing, "inferred")

    def test_stomach_does_not_match_ac_substring(self) -> None:
        self.assertEqual(
            socratic_tutor.infer_topic_id_from_question("what is a stomach"),
            "G7_C12_BIO_SYSTEMS",
        )
        self.assertEqual(
            socratic_tutor._score_text_for_topic(
                "what is a stomach", "G7_C3_ELE_CURRENTS"
            ),
            0,
        )

    def test_ac_as_whole_word_still_routes_to_currents(self) -> None:
        self.assertEqual(
            socratic_tutor.infer_topic_id_from_question("What is AC?"),
            "G7_C3_ELE_CURRENTS",
        )

    def test_stomach_switches_away_from_electric_currents(self) -> None:
        socratic_tutor._last_resolved_topic_by_user[self.user_id] = (
            "G7_C3_ELE_CURRENTS"
        )
        topic, routing = socratic_tutor._resolve_topic_for_turn(
            self.user_id,
            "what is a stomach",
            None,
            [{"role": "assistant", "content": "Which source powers a flashlight?"}],
        )

        self.assertEqual(topic, "G7_C12_BIO_SYSTEMS")
        self.assertEqual(routing, "switched")


if __name__ == "__main__":
    unittest.main()
