import unittest

from reconstruction import score_reconstruction


class ReconstructionTests(unittest.TestCase):
    def test_free_text_communication_is_not_numerically_scored(self):
        turns = [{
            "role": "Reporting",
            "tool_call": {
                "name": "send_report",
                "arguments": {"text": "Policy A appears more profitable."},
            },
        }]
        scored = score_reconstruction({}, 0.5, turns)
        self.assertFalse(scored["applicable"])
        self.assertEqual(scored["records"], [])
        self.assertIsNone(scored["local_within_1pct_fraction"])
        self.assertIn("free text", scored["scope"])


if __name__ == "__main__":
    unittest.main()
