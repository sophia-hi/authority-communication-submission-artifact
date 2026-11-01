import unittest
from pathlib import Path

import yaml

from calculate import CALCULATOR_TOOL
from agent_interface import (
    AgentInterfaceError, organization_rules_brief, parse_single_tool_call,
    role_dossier, system_instructions, tool_schemas,
)
from organizations import SPECS
from seed_design import build_frame


class AgentInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text())
        cls.family = build_frame(cfg)[0][0]

    def test_owner_gets_both_local_binders_and_specialist_gets_one(self):
        owner = role_dossier(self.family, 0.5, "single", "Owner")
        specialist = role_dossier(
            self.family, 0.5, "mutual", "Branch 1 Specialist")
        self.assertIn("Branch 1 local binder", owner)
        self.assertIn("Branch 2 local binder", owner)
        self.assertIn("Branch 1 local binder", specialist)
        self.assertNotIn("Branch 2 local binder", specialist)

    def test_all_communication_payloads_are_free_text(self):
        for name in ("send_message", "send_report"):
            with self.subTest(tool=name):
                schema = tool_schemas({name})[0]["parameters"]
                self.assertEqual(set(schema["properties"]), {"text"})
                self.assertEqual(schema["required"], ["text"])
        handoff = tool_schemas({"commit_and_handoff"})[0]["parameters"]
        self.assertEqual(set(handoff["properties"]), {"action", "text"})
        self.assertEqual(handoff["required"], ["action", "text"])

    def test_final_submission_tools_contain_actions_only(self):
        company = tool_schemas({"submit_company"})[0]["parameters"]
        branch = tool_schemas({"submit_branch"})[0]["parameters"]
        self.assertEqual(set(company["properties"]), {"branch1", "branch2"})
        self.assertEqual(company["required"], ["branch1", "branch2"])
        self.assertEqual(set(branch["properties"]), {"action"})
        self.assertEqual(branch["required"], ["action"])

    def test_common_calculator_schema_is_private_numeric_input_only(self):
        calculator = tool_schemas({CALCULATOR_TOOL})[0]
        self.assertEqual(calculator["name"], "calculate_batch")
        self.assertEqual(
            set(calculator["parameters"]["properties"]), {"expressions"})
        self.assertIn("cannot read binders", calculator["description"])
        self.assertIn("does not communicate", calculator["description"])
        self.assertIn("Percent notation", calculator["description"])
        self.assertIn("at most 24 expressions", calculator["description"])
        self.assertIn("exponent's absolute value", calculator["description"])

    def test_parser_requires_exactly_one_allowed_call(self):
        call = {"type": "function_call", "call_id": "c1",
                "name": "submit_branch", "arguments": '{"action":"A"}'}
        parsed = parse_single_tool_call([call], {"submit_branch"})
        self.assertEqual(parsed.arguments, {"action": "A"})
        with self.assertRaises(AgentInterfaceError):
            parse_single_tool_call([], {"submit_branch"})
        with self.assertRaises(AgentInterfaceError):
            parse_single_tool_call([call], {"send_report"})

    def test_every_role_receives_complete_rules_brief_from_common_template(self):
        for organization in SPECS:
            if organization == "single":
                roles = [("Owner", None)]
            elif organization in {"independent", "mutual"}:
                roles = [
                    ("Branch 1 Specialist", 0),
                    ("Branch 2 Specialist", 1),
                ]
            else:
                lead = self.family["lead_branch_index"]
                roles = [("Lead", lead), ("Reporting", 1 - lead)]
            for role, branch_index in roles:
                with self.subTest(organization=organization, role=role):
                    prompt = system_instructions(organization, role, branch_index)
                    self.assertIn("# Organization rules", prompt)
                    self.assertIn("## Company objective and decision principle", prompt)
                    self.assertIn("## Information structure", prompt)
                    self.assertIn("## Final decision authority", prompt)
                    self.assertIn("## Communication", prompt)
                    self.assertIn("## Decision sequence", prompt)
                    self.assertIn("## Submission finality and visibility", prompt)
                    self.assertNotIn("lead_branch", prompt)
                    self.assertNotIn("reporting_branch", prompt)
                    self.assertEqual(
                        prompt.count("Maximize total company annual profit"), 1)

    def test_company_objective_does_not_require_private_partner_data(self):
        brief = organization_rules_brief(
            "independent", "Branch 1 Specialist", 0)
        self.assertIn("given the information available to you", brief)
        self.assertIn("not expected to access or calculate from a partner's private local binder", brief)

    def test_rules_state_partner_information_and_authority_without_private_data(self):
        lead = self.family["lead_branch_index"]
        decentralized = organization_rules_brief(
            "mutual", "Branch 1 Specialist", 0)
        centralized = organization_rules_brief(
            "centralized_two_way", "Reporting", 1 - lead)
        self.assertIn("Neither specialist can directly access", decentralized)
        self.assertIn("Branch 1 Specialist submits only", decentralized)
        self.assertIn("Branch 2 Specialist submits only", decentralized)
        self.assertIn("Lead alone submits", centralized)
        self.assertIn("has no final decision right", centralized)
        self.assertNotIn("base_units", decentralized)
        self.assertNotIn("reference_price", centralized)

    def test_rules_match_key_protocol_sequences(self):
        lead = self.family["lead_branch_index"]
        communicating = (
            "committed_handoff", "informational_handoff", "mutual",
            "specialist_proactive", "centralized_two_way")
        common = (
            "No final submission is available during the opening.",
            "A message sent in the same round as a submission, decline, or finish does not cancel that action",
            "Decline passes this round only.",
            "Finish permanently closes communication without filing a decision.",
        )
        for organization in communicating:
            role = "Branch 1 Specialist" if organization == "mutual" else "Lead"
            branch = 0 if organization == "mutual" else lead
            brief = organization_rules_brief(organization, role, branch)
            for phrase in common:
                with self.subTest(organization=organization, phrase=phrase):
                    self.assertIn(phrase, brief)
            self.assertNotIn("recipient reads the message and decides again", brief)
            self.assertNotIn("sender sits out", brief)
        informational = organization_rules_brief(
            "informational_handoff", "Lead", lead)
        committed = organization_rules_brief("committed_handoff", "Lead", lead)
        mutual = organization_rules_brief("mutual", "Branch 1 Specialist", 0)
        self.assertIn("its later filing may differ", informational)
        self.assertIn("actual irreversible branch decision", committed)
        self.assertIn("A filed specialist may still communicate", mutual)

    def test_communicating_roles_share_the_same_message_content_rule(self):
        phrase = (
            "Messages may contain economic analyses, recommendations, intended "
            "choices, or already-filed choices")
        for organization in (
                "committed_handoff", "informational_handoff", "mutual",
                "specialist_proactive", "centralized_two_way"):
            if organization == "mutual":
                brief = organization_rules_brief(
                    organization, "Branch 1 Specialist", 0)
            else:
                lead = self.family["lead_branch_index"]
                brief = organization_rules_brief(organization, "Lead", lead)
            self.assertEqual(brief.count(phrase), 1)

    def test_h3_organizations_use_the_same_neutral_visible_role_names(self):
        lead = self.family["lead_branch_index"]
        reporting = 1 - lead
        for organization in ("informational_handoff", "committed_handoff"):
            with self.subTest(organization=organization, role="Lead"):
                prompt = system_instructions(organization, "Lead", lead)
                self.assertIn("You are the Receiving Specialist role", prompt)
                self.assertNotIn("You are the Lead", prompt)
            with self.subTest(organization=organization, role="Reporting"):
                prompt = system_instructions(
                    organization, "Reporting", reporting)
                self.assertIn("You are the Reporting Specialist role", prompt)

    def test_informational_handoff_uses_neutral_visible_roles(self):
        lead = self.family["lead_branch_index"]
        prompt = system_instructions("informational_handoff", "Lead", lead)
        self.assertIn("You are the Receiving Specialist role", prompt)
        self.assertNotIn("You are the Lead", prompt)
        self.assertIn("intended choice is non-binding", prompt)
        self.assertIn("its later filing may differ", prompt)

    def test_equal_decentralized_agent_text_has_no_hierarchical_role_names(self):
        for organization in ("independent", "mutual"):
            for role, branch_index in (
                    ("Branch 1 Specialist", 0),
                    ("Branch 2 Specialist", 1)):
                prompt = system_instructions(
                    organization, role, branch_index)
                self.assertNotIn("Lead", prompt)
                self.assertNotIn("Reporting", prompt)
                self.assertIn(role, prompt)


if __name__ == "__main__":
    unittest.main()
