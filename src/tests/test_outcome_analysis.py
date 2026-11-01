import unittest
from unittest.mock import patch

from outcome_analysis import summarize_outcome_envelopes
from scoring import score_organizational_failure


class OutcomeAnalysisTests(unittest.TestCase):
    def test_worst_plan_penalty_is_explicit_and_family_rho_specific(self):
        family = {
            "utilities": {"1.0": {"x": 10.0, "y": 7.5, "z": 9.0}},
            "labeled_optima": {"1.0": "AA"},
        }
        scored = score_organizational_failure(family, 1.0)
        self.assertFalse(scored["valid_submission"])
        self.assertFalse(scored["exact_optimum"])
        self.assertEqual(scored["decision_score"], 0.0)
        self.assertEqual(scored["raw_regret_m"], 2.5)
        self.assertTrue(scored["penalty_is_scoring_convention"])

    def test_reports_unconditional_conditional_failure_and_resources(self):
        resource = {
            "model_requests": 2, "recorded_model_responses": 2,
            "request_retries": 0, "retry_wait_s": 0.0,
            "failed_request_time_s": 0.0,
            "requests_with_unknown_usage": 0,
            "usage_complete": True,
            "input_tokens": 20, "output_tokens": 4,
            "reasoning_tokens": 1, "total_tokens": 24,
            "known_input_tokens": 20, "known_output_tokens": 4,
            "known_reasoning_tokens": 1, "known_total_tokens": 24,
            "communication_actions": 1, "provider_latency_s": 0.5,
            "queue_delay_s": 0.1, "wall_time_s": 0.8,
            "parallel_overlap_s": 0.2, "cost_usd": 0.01,
            "known_cost_usd": 0.01, "requests_with_unknown_cost": 0,
            "cost_complete": True,
            "role_active_time_s": {"Lead": 0.5},
            "role_queue_delay_s": {"Lead": 0.1},
            "calculator_calls": 1, "calculator_expressions": 2,
            "calculator_time_s": 0.001,
        }
        calculator_calls = [{
            "calculator_call_id": 1,
            "role": "Branch 1 Specialist",
            "model_turn_number": 1,
            "input": {"expressions": ["1 + 1", "2 + 2"]},
            "output": {"accepted": True, "n": 2, "n_ok": 2,
                       "results": []},
            "expression_count": 2,
            "started_at_s": 0.1,
            "completed_at_s": 0.101,
            "duration_s": 0.001,
        }]
        common = {
            "data_schema_version": "authority_communication_data_v9",
            "family_id": 1, "candidate_id": 1, "rho": 1.0,
            "organization": "mutual", "lead_branch_index": 0,
            "reporting_branch_index": 1,
            "economic_family": {
                "design_version": "test", "master_seed": 1,
                "economic_generator_version": "branch_pricing_v1",
                "candidate_id": 1, "rng_draws": 1,
                "branch_primitives": [{}, {}], "local": [{}, {}],
                "interaction_primitives": {}, "interaction": {},
                "utilities": {"1.0": {
                    "standard|standard": 9.8,
                    "standard|premium": 10.0,
                    "premium|standard": 9.0,
                    "premium|premium": 8.0,
                }},
                "substantive_optima": {"1.0": "standard|premium"},
                "local_plan": "standard|standard", "label_maps": [
                    {"standard": "A", "premium": "B"},
                    {"standard": "A", "premium": "B"},
                ],
                "labeled_optima": {"1.0": "AB"}, "family_id": 1,
                "lead_branch_index": 0, "reporting_branch_index": 1,
                "document_template_seed": 1, "counterbalance_seed": 1,
            },
            "events": [],
            "protocol_deliveries": [], "prompt_integrity": {}, "turns": [],
            "unapplied_calls": [], "calculator_calls": calculator_calls,
            "request_errors": [],
            "accepted_branch_actions": {"1": "A", "2": "A"},
            "submission_audit": {
                "attempted": [], "accepted": [], "cancelled": []},
            "emergency_guard_hit": False,
        }
        envelopes = [
            {
                "status": "complete",
                "schedule": {"organization": "mutual", "rho": 1.0},
                "result": {
                    **common, "run_id": "valid", "submitted": "AA",
                    "valid_submission": True, "organizational_failure": False,
                    "failure_penalty": None,
                    "penalty_is_scoring_convention": False,
                    "raw_regret_m": 0.2, "decision_score": 90.0,
                    "exact_optimum": False, "resources": resource,
                },
            },
            {
                "status": "organizational_terminal",
                "schedule": {"organization": "mutual", "rho": 1.0},
                "result": {
                    **common, "run_id": "failed", "submitted": None,
                    "valid_submission": False, "organizational_failure": True,
                    "failure_penalty": "worst_plan_within_family_rho",
                    "penalty_is_scoring_convention": True,
                    "failure_category": "partial_submission",
                    "raw_regret_m": 2.0, "decision_score": 0.0,
                    "exact_optimum": False, "resources": resource,
                },
            },
            {
                "status": "infrastructure_failure",
                "schedule": {"organization": "mutual", "rho": 1.0},
            },
        ]
        with patch("outcome_analysis.validate_result_record"):
            row = summarize_outcome_envelopes(envelopes)["organization"]["mutual"]
        self.assertEqual(row["organizational_failure_rate"], 0.5)
        self.assertEqual(row["unresolved_infrastructure_failures"], 1)
        self.assertEqual(row["unconditional_performance"]["raw_regret_m"], 1.1)
        self.assertEqual(row["conditional_decision_quality"]["raw_regret_m"], 0.2)
        self.assertEqual(row["resources_for_organizational_failures"]["total_tokens"], 24)
        self.assertEqual(
            row["resources_for_organizational_failures"]["calculator_calls"], 1)

    def test_cost_reporting_keeps_partial_known_cost_separate_from_total(self):
        complete = {
            "status": "complete",
            "schedule": {"organization": "single", "rho": 0.0},
            "result": {
                "valid_submission": True,
                "organizational_failure": False,
                "resources": {
                    "model_requests": 2,
                    "known_cost_usd": 0.03,
                    "requests_with_unknown_cost": 1,
                    "cost_complete": False,
                    "cost_usd": None,
                },
            },
        }
        # This focused summary test bypasses schema validation because the
        # minimal fixture intentionally contains only resource fields.
        from unittest.mock import patch
        with patch("outcome_analysis.validate_result_record"):
            row = summarize_outcome_envelopes([complete])["organization"]["single"]
        cost = row["cost_reporting"]
        self.assertEqual(cost["known_cost_subtotal_usd"], 0.03)
        self.assertIsNone(cost["total_cost_usd"])
        self.assertFalse(cost["cost_complete"])
        self.assertEqual(cost["requests_with_unknown_cost"], 1)
        self.assertEqual(cost["request_cost_missing_rate"], 0.5)

    def test_usage_reporting_does_not_treat_missing_tokens_as_zero(self):
        envelope = {
            "status": "complete",
            "schedule": {"organization": "single", "rho": 0.0},
            "result": {
                "valid_submission": True, "organizational_failure": False,
                "resources": {
                    "model_requests": 1, "usage_complete": False,
                    "requests_with_unknown_usage": 1,
                    "total_tokens": None,
                },
            },
        }
        from unittest.mock import patch
        with patch("outcome_analysis.validate_result_record"):
            row = summarize_outcome_envelopes([envelope])["organization"]["single"]
        self.assertIsNone(row["resources_per_analyzable_cell"]["total_tokens"])
        self.assertEqual(row["usage_reporting"]["cells_with_incomplete_usage"], 1)
        self.assertFalse(row["usage_reporting"]["usage_complete"])


if __name__ == "__main__":
    unittest.main()
