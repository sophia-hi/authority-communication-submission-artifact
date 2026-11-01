import unittest

from failure_policy import classify_failure
from live_cell import ModelOutputLimitError, ProviderIncompleteResponseError
from protocol import ProtocolError


class _StatusError(RuntimeError):
    def __init__(self, message: str, status_code: int, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class FailurePolicyTests(unittest.TestCase):
    def test_generic_configuration_4xx_requires_inspection(self):
        disposition = classify_failure(
            _StatusError("invalid request", 400, {"error": {"code": "bad_parameter"}}))
        self.assertEqual(disposition.category, "api_configuration_error")
        self.assertEqual(disposition.treatment, "stop_and_inspect")

    def test_rate_limit_text_cannot_masquerade_as_output_cutoff(self):
        disposition = classify_failure(
            _StatusError("rate limited while reserving output tokens", 429))
        self.assertEqual(disposition.category, "provider_network_failure")
        self.assertEqual(disposition.treatment, "inspection_required")

    def test_explicit_output_cutoff_is_organizational_terminal(self):
        disposition = classify_failure(ModelOutputLimitError("cut off"))
        self.assertEqual(disposition.category, "output_limit_cutoff")
        self.assertEqual(disposition.treatment, "organizational_terminal")

    def test_protocol_invalid_action_is_organizational_terminal(self):
        disposition = classify_failure(ProtocolError("message text is empty"))
        self.assertEqual(disposition.category, "invalid_model_action")
        self.assertEqual(disposition.treatment, "organizational_terminal")

    def test_internal_code_fault_requires_inspection(self):
        disposition = classify_failure(RuntimeError("bug"))
        self.assertEqual(disposition.category, "unexpected_exception")
        self.assertEqual(disposition.treatment, "stop_and_inspect")

    def test_explicit_provider_server_error_is_infrastructure(self):
        error = ProviderIncompleteResponseError("provider failed")
        error.model_turn = type("Turn", (), {
            "response_error": {"code": "server_error"}})()
        disposition = classify_failure(error)
        self.assertEqual(disposition.category, "provider_network_failure")
        self.assertEqual(disposition.treatment, "inspection_required")


if __name__ == "__main__":
    unittest.main()
