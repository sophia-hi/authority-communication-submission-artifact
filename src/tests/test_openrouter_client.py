import asyncio
import unittest
from types import SimpleNamespace
from pathlib import Path

import yaml

from openrouter_client import OpenRouterResponsesClient, OpenRouterSettings


class FakeResponses:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp_test",
            model="openai/gpt-test",
            status="completed",
            incomplete_details=None,
            error=None,
            output_text="done",
            output=[SimpleNamespace(type="message", role="assistant")],
            usage=SimpleNamespace(
                input_tokens=101,
                output_tokens=19,
                output_tokens_details=SimpleNamespace(reasoning_tokens=7),
            ),
            model_extra={
                "openrouter_metadata": {
                    "generation_id": "gen_test",
                    "cost": 0.001,
                    "endpoints": {"available": [{
                        "provider": "OpenAI",
                        "model": "openai/gpt-test-20261001",
                        "selected": True,
                    }]},
                }
            },
        )


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


class OpenRouterClientTests(unittest.TestCase):
    def test_default_request_matches_collection_config(self):
        runtime = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "config.yaml").read_text())["runtime"]
        fake = FakeClient()
        settings = OpenRouterSettings(model=runtime["model"], api_key="test-key")
        client = OpenRouterResponsesClient(settings, client=fake)
        turn = asyncio.run(client.create_response(input_items="task"))
        sent = fake.responses.kwargs
        self.assertEqual(sent["reasoning"]["effort"], runtime["reasoning_effort"])
        self.assertIsNone(runtime["temperature"])
        self.assertNotIn("temperature", sent)
        self.assertEqual(sent["max_output_tokens"], runtime["max_output_tokens_per_request"])
        self.assertEqual(sent["extra_body"]["provider"]["order"], runtime["openrouter_provider_order"])
        self.assertFalse(sent["extra_body"]["provider"]["allow_fallbacks"])
        self.assertIsNone(turn.request_parameters["temperature"])

    def test_settings_reject_missing_key_and_fallback(self):
        with self.assertRaises(ValueError):
            OpenRouterSettings(model="openai/gpt-test", api_key="")
        with self.assertRaises(ValueError):
            OpenRouterSettings(
                model="openai/gpt-test",
                api_key="secret",
                allow_model_fallback=True,
            )

    def test_request_is_pinned_and_response_is_auditable(self):
        fake = FakeClient()
        settings = OpenRouterSettings(
            model="openai/gpt-test",
            api_key="secret",
            provider_order=("OpenAI",),
            max_output_tokens=500,
        )
        client = OpenRouterResponsesClient(settings, client=fake)
        turn = asyncio.run(client.create_response(
            input_items="task",
            tools=[{"type": "function", "name": "submit_company"}],
            metadata={"cell_id": "c1"},
            session_id="session-c1",
        ))

        sent = fake.responses.kwargs
        self.assertEqual(sent["model"], "openai/gpt-test")
        self.assertNotIn("parallel_tool_calls", sent)
        self.assertEqual(sent["tool_choice"], "required")
        self.assertFalse(sent["store"])
        self.assertEqual(sent["extra_body"]["provider"], {
            "allow_fallbacks": False,
            "require_parameters": True,
            "order": ["OpenAI"],
        })
        self.assertEqual(sent["extra_body"]["session_id"], "session-c1")
        self.assertEqual(turn.requested_model, "openai/gpt-test")
        self.assertEqual(turn.returned_model, "openai/gpt-test")
        self.assertEqual(turn.served_endpoint_model,
                         "openai/gpt-test-20261001")
        self.assertEqual(turn.provider, "OpenAI")
        self.assertEqual(turn.usage["input_tokens"], 101)
        self.assertEqual(turn.usage["cost"], 0.001)
        self.assertEqual(turn.response_status, "completed")
        self.assertIsNone(turn.incomplete_details)
        self.assertIsNone(turn.response_error)
        self.assertEqual(turn.openrouter_metadata["generation_id"], "gen_test")
        self.assertNotIn("secret", repr(turn.to_dict()))


if __name__ == "__main__":
    unittest.main()
