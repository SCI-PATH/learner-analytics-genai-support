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


if __name__ == "__main__":
    unittest.main()
