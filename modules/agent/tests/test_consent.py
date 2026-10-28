"""Consent registration persists for the next ingest turn.

Run: python3 -m pytest -q modules/agent/tests/test_consent.py
"""

import importlib.util
import io
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
    "USERS_TABLE": "users",
    "AUDIT_TABLE": "audit",
    "INGEST_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/000000000000/q.fifo",
    "MEDIA_BUCKET": "media",
    "MEDIA_STATE_MACHINE_ARN": "arn:aws:states:us-east-1:000000000000:stateMachine:media",
})

_strands = mock.MagicMock()
sys.modules.setdefault("strands", _strands).tool = lambda fn: fn
sys.modules.setdefault("strands.models.bedrock", mock.MagicMock())
_exceptions = mock.MagicMock()
_exceptions.ModelThrottledException = type("ModelThrottled", (Exception,), {})
sys.modules.setdefault("strands.types.exceptions", _exceptions)

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_ROOT, *path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent = _load("consent_agent", ("agent", "src", "agent", "handler.py"))
register_consent = _load(
    "consent_register_consent", ("agent", "src", "register_consent", "handler.py"),
)
ingest = _load("consent_ingest", ("compute", "src", "ingest", "handler.py"))

SENDER = "5215512345678"
SENDER_PLUS = "+" + SENDER
ORIGIN = "arn:aws:social-messaging:us-east-1:000000000000:phone-number-id/abc"


class FakeDynamo:
    def __init__(self):
        self.tables = {}

    def _key(self, Key):
        if "user_id" in Key:
            return Key["user_id"]["S"]
        return json.dumps(Key, sort_keys=True)

    def get_item(self, TableName, Key, **kwargs):
        item = self.tables.get(TableName, {}).get(self._key(Key))
        return {"Item": item} if item else {}

    def update_item(self, TableName, Key, UpdateExpression="",
                    ExpressionAttributeValues=None, ExpressionAttributeNames=None,
                    **kwargs):
        table = self.tables.setdefault(TableName, {})
        item_key = self._key(Key)
        item = table.setdefault(item_key, dict(Key))
        values = ExpressionAttributeValues or {}
        names = ExpressionAttributeNames or {}
        expr = UpdateExpression.strip()
        if expr.startswith("ADD "):
            _, rest = expr.split(" ", 1)
            attr_token, val_token = rest.split()
            attr = names.get(attr_token, attr_token)
            addend = int(values[val_token]["N"])
            current = int(item.get(attr, {}).get("N", "0"))
            item[attr] = {"N": str(current + addend)}
            return {"Attributes": {attr: item[attr]}}
        if "SET" in expr:
            rest = expr.split("SET", 1)[1]
            for part in rest.split(","):
                left, right = part.strip().split("=")
                attr = names.get(left.strip(), left.strip())
                item[attr] = values[right.strip()]
        return {"Attributes": item}

    def put_item(self, TableName, Item, **kwargs):
        table = self.tables.setdefault(TableName, {})
        if "user_id" in Item:
            table[Item["user_id"]["S"]] = Item
        else:
            table[json.dumps(Item, sort_keys=True)] = Item
        return {}


class _Result:
    def __str__(self):
        return "Listo."

    message = None


class _ScriptedAgent:
    mode = "accept"
    system_prompts = []
    tools = []
    also_report = False
    create_report_calls = 0
    last_consent_pending = None

    def __init__(self, **kwargs):
        _ScriptedAgent.system_prompts.append(kwargs.get("system_prompt") or "")
        _ScriptedAgent.tools.append(kwargs.get("tools") or [])

    def __call__(self, prompt):
        if _ScriptedAgent.mode == "accept":
            agent.register_consent()
            _ScriptedAgent.last_consent_pending = agent._turn.get("consent_pending")
            if _ScriptedAgent.also_report:
                agent.create_report(
                    category="transito", geohash="9g3qrbc",
                    description="Patrulla estacionada",
                )
                _ScriptedAgent.create_report_calls += 1
        return _Result()


def _invoke_tool(FunctionName, InvocationType, Payload):
    payload = json.loads(Payload)
    if FunctionName == "register-consent":
        result = register_consent.lambda_handler(payload, None)
    elif FunctionName == "create-report":
        result = {"ok": True, "report_id": "r1"}
    else:
        result = {"ok": False, "error": "unknown_tool"}
    return {"Payload": io.BytesIO(json.dumps(result).encode())}


class ConsentRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.ddb = FakeDynamo()
        ingest._ddb = self.ddb
        register_consent._ddb = self.ddb
        ingest._sqs = mock.MagicMock()
        ingest._sfn = mock.MagicMock()
        ingest._already_processed = lambda *a, **k: False
        ingest._check_rate_limit = lambda *a, **k: False
        agent.Agent = _ScriptedAgent
        agent.BedrockModel = mock.MagicMock()
        agent._lambda = mock.MagicMock()
        agent._lambda.invoke.side_effect = _invoke_tool
        agent.TOOL_REGISTER_CONSENT_FN = "register-consent"
        agent.TOOL_CREATE_REPORT_FN = "create-report"
        agent.TOOL_FOLLOW_UP_FN = ""
        _ScriptedAgent.mode = "accept"
        _ScriptedAgent.system_prompts = []
        _ScriptedAgent.tools = []
        _ScriptedAgent.also_report = False
        _ScriptedAgent.create_report_calls = 0
        _ScriptedAgent.last_consent_pending = None

    def _queued(self):
        return json.loads(ingest._sqs.send_message.call_args.kwargs["MessageBody"])

    def _ingest(self, user_id, text, message_id):
        ingest._sqs.send_message.reset_mock()
        ingest._process_item({
            "user_id": user_id,
            "message_id": message_id,
            "type": "text",
            "text": text,
            "origination_phone_number_id": ORIGIN,
        })
        return self._queued()

    def _turn(self, user_id, text, consent_pending=True):
        return agent.lambda_handler({
            "user_id": user_id,
            "text": text,
            "message_id": "wamid.consent",
            "type": "text",
            "consent_pending": consent_pending,
        }, None)

    def test_accept_registers_and_next_ingest_is_not_pending(self):
        first = self._ingest(SENDER, "SI ACEPTO", "wamid.1")
        self.assertTrue(first["consent_pending"])
        self.assertTrue(self._turn(SENDER, "SI ACEPTO")["ok"])
        self.assertTrue(ingest._check_consent(SENDER))
        next_msg = self._ingest(
            SENDER,
            "Crea un reporte para Patrulla estacionada bloquea el carril en la esquina",
            "wamid.2",
        )
        self.assertFalse(next_msg["consent_pending"])

    def test_plus_e164_and_bare_e164_share_the_consent_record(self):
        self.assertTrue(self._turn(SENDER_PLUS, "SI ACEPTO")["ok"])
        self.assertTrue(ingest._check_consent(SENDER))
        self.assertTrue(ingest._check_consent(SENDER_PLUS))
        next_msg = self._ingest(SENDER, "foto del carril", "wamid.plus")
        self.assertFalse(next_msg["consent_pending"])

    def test_reject_does_not_register(self):
        _ScriptedAgent.mode = "skip"
        self.assertTrue(self._turn(SENDER, "No, no acepto")["ok"])
        self.assertFalse(ingest._check_consent(SENDER))
        next_msg = self._ingest(SENDER, "No, no acepto", "wamid.no")
        self.assertTrue(next_msg["consent_pending"])

    def test_ambiguous_does_not_register(self):
        _ScriptedAgent.mode = "skip"
        self.assertTrue(self._turn(SENDER, "luego veo")["ok"])
        self.assertFalse(ingest._check_consent(SENDER))
        next_msg = self._ingest(SENDER, "luego veo", "wamid.maybe")
        self.assertTrue(next_msg["consent_pending"])

    def test_same_turn_after_accept_is_no_longer_pending(self):
        _ScriptedAgent.also_report = True
        self.assertTrue(self._turn(
            SENDER,
            "SI ACEPTO. Crea un reporte para Patrulla estacionada",
        )["ok"])
        self.assertIs(False, _ScriptedAgent.last_consent_pending)
        self.assertEqual(_ScriptedAgent.create_report_calls, 1)
        self.assertTrue(ingest._check_consent(SENDER))

    def test_prompt_forbids_claiming_registration_without_tool_ok(self):
        self.assertTrue(self._turn(SENDER, "SI ACEPTO")["ok"])
        prompt = _ScriptedAgent.system_prompts[-1].lower()
        self.assertIn("register_consent", prompt)
        self.assertIn("herramienta", prompt)
        self.assertTrue(
            "ok" in prompt and "afirm" in prompt,
            prompt,
        )
        tool_names = [fn.__name__ for fn in _ScriptedAgent.tools[-1]]
        self.assertIn("register_consent", tool_names)
