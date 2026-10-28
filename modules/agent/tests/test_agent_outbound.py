"""Simulated WhatsApp outbound log on the agent Lambda.

Run: python3 -m unittest discover -s modules/agent/tests
"""

import hashlib
import json
import os
import sys
import unittest
from unittest import mock

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "SIMULATE_WHATSAPP_REPLY": "",
})

_strands = mock.MagicMock()
_exceptions = mock.MagicMock()


class _ModelThrottled(Exception):
    pass


_exceptions.ModelThrottledException = _ModelThrottled
sys.modules.setdefault("strands", _strands)
sys.modules.setdefault("strands.models.bedrock", mock.MagicMock())
sys.modules.setdefault("strands.types.exceptions", _exceptions)

import importlib.util

_HANDLER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "agent", "handler.py",
)
_spec = importlib.util.spec_from_file_location(
    "urbanbot_agent_handler", _HANDLER_PATH,
)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)

SENDER = "5215599900001"
REPLY = "Claro, cuentame el problema y la ubicacion."
WAMID = "wamid.SMOKE-test1"


class _Result:
    def __str__(self):
        return REPLY

    message = None


class _Agent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __call__(self, prompt):
        self.prompt = prompt
        return _Result()


class SimulatedOutboundTests(unittest.TestCase):
    def setUp(self):
        handler.Agent = _Agent
        handler.BedrockModel = mock.MagicMock()
        handler._lambda = mock.MagicMock()

    def tearDown(self):
        os.environ.pop("SMOKE_TEST_NUMBER", None)

    def _event(self, sender=SENDER):
        return {
            "user_id": sender,
            "text": "hola",
            "message_id": WAMID,
            "type": "text",
        }

    def _would_send(self, output):
        events = []
        for line in output:
            payload = json.loads(line.split(":", 2)[2])
            if payload.get("event") == "WOULD_SEND_REPLY":
                events.append(payload)
        return events

    def test_env_on_smoke_sender_logs_metadata_without_text(self):
        os.environ["SIMULATE_WHATSAPP_REPLY"] = "1"
        with self.assertLogs(handler.logger, level="INFO") as cm:
            result = handler.lambda_handler(self._event(), None)
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("reply"), REPLY)
        events = self._would_send(cm.output)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["message_id"], WAMID)
        self.assertEqual(event["recipient"], "****0001")
        self.assertEqual(event["text_len"], len(REPLY))
        self.assertEqual(
            event["text_hash"],
            hashlib.sha256(REPLY.encode("utf-8")).hexdigest()[:16],
        )
        self.assertNotIn("text", event)
        joined = " ".join(cm.output)
        self.assertNotIn(REPLY, joined)
        self.assertNotIn(SENDER, joined)

    def test_env_on_real_sender_skips_would_send_reply(self):
        os.environ["SIMULATE_WHATSAPP_REPLY"] = "1"
        with self.assertLogs(handler.logger, level="INFO") as cm:
            result = handler.lambda_handler(self._event("5215512345678"), None)
        self.assertTrue(result.get("ok"))
        self.assertEqual(self._would_send(cm.output), [])

    def test_smoke_number_is_configurable(self):
        os.environ["SIMULATE_WHATSAPP_REPLY"] = "1"
        os.environ["SMOKE_TEST_NUMBER"] = "5215512345678"
        with self.assertLogs(handler.logger, level="INFO") as cm:
            handler.lambda_handler(self._event("5215512345678"), None)
            handler.lambda_handler(self._event(), None)
        events = self._would_send(cm.output)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["recipient"], "****5678")

    def test_env_off_skips_would_send_reply(self):
        os.environ["SIMULATE_WHATSAPP_REPLY"] = "0"
        with self.assertLogs(handler.logger, level="INFO") as cm:
            result = handler.lambda_handler(self._event(), None)
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("reply"), REPLY)
        self.assertEqual(self._would_send(cm.output), [])
        self.assertNotIn(REPLY, " ".join(cm.output))

    def test_invalid_input_does_not_simulate_send(self):
        os.environ["SIMULATE_WHATSAPP_REPLY"] = "1"
        with self.assertLogs(handler.logger, level="WARNING") as cm:
            result = handler.lambda_handler({"user_id": SENDER, "text": ""}, None)
        self.assertFalse(result.get("ok"))
        self.assertNotIn("WOULD_SEND_REPLY", " ".join(cm.output))


if __name__ == "__main__":
    unittest.main()
