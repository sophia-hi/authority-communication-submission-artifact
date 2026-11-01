import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from protocol import ProtocolError, ProtocolState
from mock_runner import run_mock_cell
import yaml
from seed_design import build_frame
from organizations import SPECS


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = yaml.safe_load((HERE / "config.yaml").read_text())
        cls.family = build_frame(cfg)[0][0]

    def test_committed_handoff_is_irreversible_and_direction_balanced(self):
        for lead in (0, 1):
            s = ProtocolState("committed_handoff", lead)
            self.assertEqual(s.allowed_actions("Lead"), set())
            s.commit_and_handoff("Reporting", "B", "economics and committed B")
            self.assertEqual(
                s.allowed_actions("Reporting"),
                {"send_message", "decline_message", "finish_communication"})
            self.assertEqual(
                s.allowed_actions("Lead"),
                {"submit_branch", "decline_message", "finish_communication"})
            s.submit_branch("Lead", "A")
            expected = ("A", "B") if lead == 0 else ("B", "A")
            self.assertEqual(s.assembled_actions(), expected)
            with self.assertRaises(ProtocolError):
                s.submit_branch("Reporting", "A")

    def test_informational_handoff_reports_then_submits_separately(self):
        s = ProtocolState("informational_handoff", 0)
        self.assertEqual(s.allowed_actions("Reporting"), {"send_report"})
        s.send_report("Reporting", "local sufficient statistics only")
        self.assertEqual(s.allowed_actions("Reporting"), {
            "submit_branch", "send_message", "decline_message",
            "finish_communication",
        })
        self.assertEqual(s.allowed_actions("Lead"), {
            "submit_branch", "decline_message", "finish_communication",
        })
        s.submit_branch("Reporting", "B")
        s.submit_branch("Lead", "A")
        self.assertEqual(s.assembled_actions(), ("A", "B"))

    def test_two_way_arms_have_no_protocol_message_cap(self):
        role_pairs = {
            "mutual": ("Branch 1 Specialist", "Branch 2 Specialist"),
            "centralized_two_way": ("Lead", "Reporting"),
        }
        for org, roles in role_pairs.items():
            s = ProtocolState(org, 0)
            s.send_message(roles[0], "mandatory opening")
            s.send_message(roles[1], "mandatory opening")
            for _ in range(100):
                s.send_message(roles[0], "question")
                s.send_message(roles[1], "answer")
            self.assertEqual(len(s.events), 202)

    def test_mutual_uses_equal_branch_specialists(self):
        s = ProtocolState("mutual", 1)
        self.assertEqual(
            s.allowed_actions("Branch 1 Specialist"), {"send_message"})
        self.assertEqual(
            s.allowed_actions("Branch 2 Specialist"), {"send_message"})
        s.send_message("Branch 1 Specialist", "mandatory opening")
        self.assertEqual(s.allowed_actions("Branch 1 Specialist"), set())
        s.send_message("Branch 2 Specialist", "mandatory opening")
        open_actions = {
            "decline_message", "finish_communication", "send_message",
            "submit_branch",
        }
        self.assertEqual(
            s.allowed_actions("Branch 1 Specialist"),
            open_actions)
        self.assertEqual(
            s.allowed_actions("Branch 2 Specialist"),
            open_actions)
        self.assertEqual(s.allowed_actions("Lead"), set())
        self.assertEqual(s.allowed_actions("Reporting"), set())
        s.submit_branch("Branch 1 Specialist", "A")
        self.assertEqual(
            s.allowed_actions("Branch 1 Specialist"),
            {"decline_message", "finish_communication", "send_message"})
        self.assertEqual(s.allowed_actions("Branch 2 Specialist"), open_actions)
        with self.assertRaises(ProtocolError):
            s.submit_branch("Branch 1 Specialist", "B")
        s.send_message("Branch 1 Specialist", "post-submission analysis")
        s.submit_branch("Branch 2 Specialist", "B")
        self.assertEqual(s.assembled_actions(), ("A", "B"))

    def test_mutual_finishing_communication_preserves_unfiled_decision_right(self):
        s = ProtocolState("mutual", 0)
        s.send_message("Branch 1 Specialist", "mandatory opening")
        s.send_message("Branch 2 Specialist", "mandatory opening")
        s.finish_communication("Branch 1 Specialist")
        self.assertEqual(
            s.allowed_actions("Branch 1 Specialist"), {"submit_branch"})
        self.assertEqual(
            s.allowed_actions("Branch 2 Specialist"),
            {"submit_branch"})
        with self.assertRaises(ProtocolError):
            s.finish_communication("Branch 2 Specialist")
        self.assertEqual(
            s.allowed_actions("Branch 2 Specialist"), {"submit_branch"})
        s.submit_branch("Branch 1 Specialist", "A")
        s.submit_branch("Branch 2 Specialist", "B")
        self.assertEqual(s.assembled_actions(), ("A", "B"))

    def test_centralized_two_way_requires_both_opening_messages(self):
        s = ProtocolState("centralized_two_way", 0)
        self.assertEqual(s.allowed_actions("Lead"), {"send_message"})
        self.assertEqual(s.allowed_actions("Reporting"), {"send_message"})
        with self.assertRaises(ProtocolError):
            s.submit_company("Lead", "A", "A")
        s.send_message("Lead", "mandatory opening")
        s.send_message("Reporting", "mandatory opening")
        self.assertIn("submit_company", s.allowed_actions("Lead"))
        s.submit_company("Lead", "A", "A")

    def test_centralized_reporting_can_decline_or_end_communication(self):
        declining = ProtocolState("centralized_two_way", 0)
        declining.send_message("Lead", "mandatory opening")
        declining.send_message("Reporting", "mandatory opening")
        declining.decline_message("Reporting")
        self.assertEqual(
            declining.allowed_actions("Reporting"),
            {"decline_message", "finish_communication", "send_message"})

        finishing = ProtocolState("centralized_two_way", 0)
        finishing.send_message("Lead", "mandatory opening")
        finishing.send_message("Reporting", "mandatory opening")
        finishing.finish_communication("Reporting")
        self.assertEqual(finishing.allowed_actions("Reporting"), set())
        self.assertEqual(
            finishing.allowed_actions("Lead"),
            {"submit_company"})

    def test_one_way_initial_message_is_mandatory_and_direction_is_enforced(self):
        for organization in ("informational_handoff", "specialist_proactive"):
            state = ProtocolState(organization, 0)
            self.assertEqual(state.allowed_actions("Lead"), set())
            with self.assertRaises(ProtocolError):
                if organization == "informational_handoff":
                    state.submit_branch("Lead", "A")
                else:
                    state.submit_company("Lead", "A", "A")
            with self.assertRaises(ProtocolError):
                state.send_message("Lead", "reverse message")
            state.send_report("Reporting", "mandatory opening")
            self.assertIn("send_message", state.allowed_actions("Reporting"))
            self.assertNotIn("send_message", state.allowed_actions("Lead"))

    def test_three_empty_rounds_enter_final_decision_phase(self):
        state = ProtocolState("specialist_proactive", 0)
        state.send_report("Reporting", "mandatory opening")
        state.enter_final_decision_phase("three empty rounds")
        self.assertEqual(state.allowed_actions("Lead"), {"submit_company"})
        self.assertEqual(state.allowed_actions("Reporting"), set())

    def test_independent_assembles_branch_order_not_role_order(self):
        s = ProtocolState("independent", 1)
        self.assertEqual(s.allowed_actions("Lead"), set())
        self.assertEqual(s.allowed_actions("Reporting"), set())
        s.submit_branch("Branch 2 Specialist", "B")
        s.submit_branch("Branch 1 Specialist", "A")
        self.assertEqual(s.assembled_actions(), ("A", "B"))

    def test_mock_runner_completes_all_seven_protocols(self):
        for org in SPECS:
            row = run_mock_cell(self.family, 1.0, org)
            self.assertTrue(row["exact_optimum"], org)
            self.assertEqual(row["decision_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
