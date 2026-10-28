"""Simulated WhatsApp outbound log on the agent Lambda.

Run: python3 -m unittest discover -s modules/agent/tests
"""

import hashlib
import inspect
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
sys.modules.setdefault("strands", _strands).tool = lambda fn: fn
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


class _CapturingAgent(_Agent):
    prompts = []

    def __call__(self, prompt):
        _CapturingAgent.prompts.append(prompt)
        return _Result()


class DroppedMediaPromptTests(unittest.TestCase):
    def setUp(self):
        _CapturingAgent.prompts = []
        handler.Agent = _CapturingAgent
        handler.BedrockModel = mock.MagicMock()
        handler._lambda = mock.MagicMock()

    def _run(self, text, reason, consent_pending=False):
        return handler.lambda_handler({
            "user_id": SENDER,
            "text": text,
            "message_id": WAMID,
            "type": "image",
            "media": [],
            "media_dropped": reason,
            "consent_pending": consent_pending,
        }, None)

    def test_captionless_dropped_image_still_reaches_agent(self):
        for text in (None, "", "   "):
            with self.subTest(text=text):
                _CapturingAgent.prompts = []
                result = self._run(text, "consent_pending", consent_pending=True)
                self.assertTrue(result.get("ok"))
                self.assertEqual(result.get("reply"), REPLY)
                prompt = _CapturingAgent.prompts[-1]
                self.assertIn(handler._MEDIA_DROPPED_NOTES["consent_pending"], prompt)
                self.assertIn("consent", prompt)

    def test_captioned_dropped_image_prompt_keeps_caption_and_reason(self):
        for reason in ("consent_pending", "rate_limited", "processing_error"):
            with self.subTest(reason=reason):
                result = self._run("bache en la calle", reason)
                self.assertTrue(result.get("ok"))
                prompt = _CapturingAgent.prompts[-1]
                self.assertTrue(prompt.startswith(handler._MEDIA_DROPPED_NOTES[reason]))
                self.assertIn("resend the photo", prompt)
                self.assertTrue(prompt.endswith("bache en la calle"))

    def test_text_without_dropped_media_has_no_photo_note(self):
        result = self._run("hola", None)
        self.assertTrue(result.get("ok"))
        self.assertEqual(_CapturingAgent.prompts[-1], "hola")

    def test_captionless_image_without_drop_reason_is_invalid_input(self):
        result = self._run("", None)
        self.assertEqual(result.get("error"), "invalid_input")
        self.assertEqual(_CapturingAgent.prompts, [])


class _ReportingAgent(_Agent):
    def __call__(self, prompt):
        handler.create_report(
            category="bacheo", geohash="9g3qrbc", description="bache en la calle",
        )
        return _Result()


class InboundMediaReportTests(unittest.TestCase):
    def setUp(self):
        handler.Agent = _ReportingAgent
        handler.BedrockModel = mock.MagicMock()
        handler._lambda = mock.MagicMock()
        handler._lambda.invoke.return_value = {
            "Payload": mock.MagicMock(read=lambda: b'{"ok": true}'),
        }
        handler.TOOL_CREATE_REPORT_FN = "create-report"

    def _report_payloads(self):
        return [
            json.loads(call.kwargs["Payload"])
            for call in handler._lambda.invoke.call_args_list
            if call.kwargs.get("FunctionName") == "create-report"
        ]

    def test_opted_in_captioned_image_report_carries_sanitized_key(self):
        result = handler.lambda_handler({
            "user_id": SENDER,
            "text": "bache en la calle",
            "message_id": WAMID,
            "type": "image",
            "media": ["sanitized/abc", "raw/secret.jpeg", {"id": "123"}],
            "media_dropped": None,
            "consent_pending": False,
        }, None)
        self.assertTrue(result.get("ok"))
        self.assertEqual(self._report_payloads()[0]["media"], ["sanitized/abc"])
        self.assertEqual(handler._turn, {})

    def test_media_does_not_leak_into_next_invocation(self):
        handler.lambda_handler({
            "user_id": SENDER, "text": "foto", "type": "image",
            "media": ["sanitized/abc"],
        }, None)
        handler.lambda_handler({"user_id": SENDER, "text": "otro bache", "type": "text"}, None)
        self.assertEqual([p["media"] for p in self._report_payloads()], [["sanitized/abc"], []])


OTHER_SENDER = "5215512345678"


class _AllToolsAgent(_Agent):
    prompts = []

    def __call__(self, prompt):
        _AllToolsAgent.prompts.append(prompt)
        handler.create_report(category="bacheo", geohash="9g3qrbc", description="bache")
        handler.join_incident(incident_id="inc-1", category="bacheo", geohash="9g3qrbc")
        handler.get_status()
        handler.register_consent()
        handler.register_place(alias="casa", geohash="9g3qrbc")
        return _Result()


class SenderIdentityInjectionTests(unittest.TestCase):
    _FUNCTIONS = {
        "TOOL_CREATE_REPORT_FN": "create-report",
        "TOOL_JOIN_INCIDENT_FN": "join-incident",
        "TOOL_GET_STATUS_FN": "get-status",
        "TOOL_REGISTER_CONSENT_FN": "register-consent",
        "TOOL_REGISTER_PLACE_FN": "register-place",
    }

    def setUp(self):
        _AllToolsAgent.prompts = []
        handler.Agent = _AllToolsAgent
        handler.BedrockModel = mock.MagicMock()
        handler._lambda = mock.MagicMock()
        handler._lambda.invoke.return_value = {
            "Payload": mock.MagicMock(read=lambda: b'{"ok": true}'),
        }
        for name, value in self._FUNCTIONS.items():
            setattr(handler, name, value)

    def _payloads(self):
        return [
            (call.kwargs["FunctionName"], json.loads(call.kwargs["Payload"]))
            for call in handler._lambda.invoke.call_args_list
        ]

    def test_each_tool_receives_current_sender_and_never_previous_one(self):
        handler.lambda_handler({"user_id": SENDER, "text": "hola"}, None)
        handler.lambda_handler({"user_id": OTHER_SENDER, "text": "hola"}, None)
        payloads = self._payloads()
        self.assertEqual(
            [name for name, _ in payloads],
            list(self._FUNCTIONS.values()) * 2,
        )
        self.assertEqual(
            [body["user_id"] for _, body in payloads],
            [SENDER] * 5 + [OTHER_SENDER] * 5,
        )
        self.assertEqual(handler._turn, {})

    def test_model_never_sees_user_id(self):
        for tool_fn in (handler.create_report, handler.join_incident,
                        handler.get_status, handler.register_consent,
                        handler.register_place):
            self.assertNotIn("user_id", inspect.signature(tool_fn).parameters)
        handler.lambda_handler({"user_id": SENDER, "text": "hola"}, None)
        self.assertNotIn(SENDER, _AllToolsAgent.prompts[0])
        self.assertNotIn(SENDER, handler._SYSTEM_PROMPT)

    def test_tool_call_outside_an_invocation_has_no_identity(self):
        handler.get_status()
        self.assertIsNone(self._payloads()[0][1]["user_id"])


if __name__ == "__main__":
    unittest.main()
