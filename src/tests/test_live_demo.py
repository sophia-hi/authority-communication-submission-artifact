"""Exercise the autonomous entry point offline through the actual executor."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_live_demo as demo
from openrouter_client import OpenRouterResponsesClient


class OfflineAPI:
    """Supply legal test actions, never a precomputed optimum or network call."""
    def __init__(self, endpoint="openai/gpt-6-luna-20260922"):
        self.responses = self
        self.calls = 0
        self.endpoint = endpoint

    async def create(self, **kwargs):
        self.calls += 1
        allowed = {tool["name"] for tool in kwargs["tools"]}
        for name, arguments in [
            ("submit_company", {"branch1": "A", "branch2": "A"}),
            ("submit_branch", {"action": "A"}),
            ("commit_and_handoff", {"action": "A", "text": "test handoff"}),
            ("send_report", {"text": "test opening"}),
            ("send_message", {"text": "test opening"}),
            ("wait_for_report", {}),
            ("finish_communication", {}),
            ("decline_message", {}),
        ]:
            if name in allowed:
                break
        else:
            raise AssertionError(allowed)
        return SimpleNamespace(
            id=f"test-response-{self.calls}", model=kwargs["model"],
            status="completed", incomplete_details=None, error=None,
            output_text="", output=[dict(type="function_call", name=name,
                arguments=json.dumps(arguments), call_id=f"test-call-{self.calls}")],
            usage=dict(input_tokens=10, output_tokens=5, total_tokens=15, cost=0.001),
            model_extra={"openrouter_metadata": {"provider": "OpenAI", "endpoints": {
                "available": [{"provider": "OpenAI", "model": self.endpoint, "selected": True}]}}},
        )


class LiveDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = demo.yaml.safe_load((demo.HERE / "config.yaml").read_text())
        cls.frame_and_audit = demo.build_frame(cfg)

    def invoke(self, argv, sdk=None, key="offline-test-key"):
        env = {"AUTHCOMM_OPENROUTER_API_KEY": key} if key else {}
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with patch.object(demo, "build_frame", return_value=self.frame_and_audit), patch.object(
                    demo, "OpenRouterResponsesClient", side_effect=(
                        lambda settings: OpenRouterResponsesClient(settings, client=sdk))) as factory:
                result = demo.main(argv)
                return result, factory

    def test_preview_needs_no_key_and_never_constructs_client_or_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "preview"
            result, factory = self.invoke(["--organization", "all", "--out", str(out)], key="")
            self.assertEqual(result, 0)
            factory.assert_not_called()
            self.assertFalse(out.exists())

    def test_all_seven_protocols_capture_requests_in_separate_demo_envelopes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "live"
            sdk = OfflineAPI()
            result, _ = self.invoke(["--organization", "all", "--execute-live", "--out", str(out)], sdk)
            self.assertEqual(result, 0)
            records = list(out.glob("demo__*.json"))
            self.assertEqual(len(records), 7)
            for path in records:
                raw = path.read_text()
                self.assertNotIn("offline-test-key", raw)
                envelope = json.loads(raw)
                self.assertEqual(envelope["dataset"], "autonomous_reviewer_demo")
                self.assertEqual(envelope["status"], "complete")
                self.assertEqual(envelope["result"]["submitted_plan"], "AA")
                for turn in envelope["result"]["turns"]:
                    self.assertIn("request_payload", turn["request_context"])
            self.assertGreater(sdk.calls, 7)

    def test_missing_key_and_occupied_output_stop_before_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "live"
            with self.assertRaises(SystemExit):
                self.invoke(["--execute-live", "--out", str(out)], key="")
            self.assertFalse(out.exists())
            out.mkdir()
            marker = out / "keep.txt"
            marker.write_text("keep")
            sdk = OfflineAPI()
            with self.assertRaises(SystemExit):
                self.invoke(["--execute-live", "--out", str(out)], sdk)
            self.assertEqual(sdk.calls, 0)
            self.assertEqual(marker.read_text(), "keep")
            with self.assertRaises(ValueError):
                demo.check_output(demo.ROOT / "data" / "results_demo")

    def test_endpoint_mismatch_stops_without_silently_substituting(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "mismatch"
            sdk = OfflineAPI(endpoint="unexpected-endpoint")
            result, _ = self.invoke(["--organization", "single", "--execute-live", "--out", str(out)], sdk)
            self.assertEqual(result, 3)
            self.assertEqual(sdk.calls, 1)
            envelope = json.loads(next(out.glob("demo__*.json")).read_text())
            self.assertEqual(envelope["status"], "inspection_required")


if __name__ == "__main__":
    unittest.main()
