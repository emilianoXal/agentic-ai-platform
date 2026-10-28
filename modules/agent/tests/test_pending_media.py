"""Pending sanitized media flows from ingest to a later create_report turn.

Run: python3 -m unittest discover -s modules/agent/tests
"""

import hashlib
import importlib.util
import io
import json
import os
import sys
import time
import unittest
from unittest import mock

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "PENDING_MEDIA_TABLE": "pending-media",
    "REPORTS_TABLE": "reports",
    "INCIDENTS_TABLE": "incidents",
    "AUDIT_TABLE": "audit",
    "INGEST_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/000000000000/q.fifo",
    "USERS_TABLE": "users",
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


agent = _load("pending_media_agent", ("agent", "src", "agent", "handler.py"))
create_report = _load("pending_media_create_report", ("agent", "src", "create_report", "handler.py"))
ingest = _load("pending_media_ingest", ("compute", "src", "ingest", "handler.py"))

SENDER = "5215599900001"
USER_HASH = hashlib.sha256(SENDER.encode("utf-8")).hexdigest()
ORIGIN = "arn:aws:social-messaging:us-east-1:000000000000:phone-number-id/abc"


class FakeDynamo:
    def __init__(self):
        self.tables = {}

    def _table(self, name):
        return self.tables.setdefault(name, {})

    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeValues,
                    ExpressionAttributeNames=None, **kwargs):
        key = json.dumps(Key, sort_keys=True)
        item = self._table(TableName).setdefault(key, dict(Key))
        if TableName == "pending-media":
            item[ExpressionAttributeNames["#key"]] = ExpressionAttributeValues[":exp"]
            item["expires_at"] = ExpressionAttributeValues[":exp"]
        return {}

    def delete_item(self, TableName, Key, ReturnValues):
        item = self._table(TableName).pop(json.dumps(Key, sort_keys=True), None)
        return {"Attributes": item} if item else {}

    def put_item(self, TableName, Item, **kwargs):
        self._table(TableName)[json.dumps(Item, sort_keys=True)] = Item
        return {}

    def query(self, **kwargs):
        return {"Items": []}


class _Result:
    def __str__(self):
        return "Listo."

    message = None


class _ScriptedAgent:
    calls_report = False

    def __init__(self, **kwargs):
        pass

    def __call__(self, prompt):
        _ScriptedAgent.prompts.append(prompt)
        if _ScriptedAgent.calls_report:
            agent.create_report(category="bacheo", geohash="9g3qrbc", description="bache")
        return _Result()


def _invoke_create_report(FunctionName, InvocationType, Payload):
    result = create_report.lambda_handler(json.loads(Payload), None)
    return {"Payload": io.BytesIO(json.dumps(result).encode())}


class PendingMediaSequenceTests(unittest.TestCase):
    def setUp(self):
        self.ddb = FakeDynamo()
        ingest._ddb = self.ddb
        create_report._ddb = self.ddb
        ingest._sqs = mock.MagicMock()
        ingest._sfn = mock.MagicMock()
        ingest._already_processed = lambda *a, **k: False
        ingest._check_consent = lambda *a, **k: True
        ingest._check_rate_limit = lambda *a, **k: False
        agent.Agent = _ScriptedAgent
        agent.BedrockModel = mock.MagicMock()
        agent._lambda = mock.MagicMock()
        agent._lambda.invoke.side_effect = _invoke_create_report
        agent.TOOL_CREATE_REPORT_FN = "create-report"
        _ScriptedAgent.prompts = []

    def _inbound(self, message_id, text, image=False):
        item = {
            "user_id": SENDER,
            "message_id": message_id,
            "type": "image" if image else "text",
            "text": text,
            "origination_phone_number_id": ORIGIN,
        }
        if image:
            item["media"] = {"id": "media-" + message_id}
        ingest._sqs.send_message.reset_mock()
        ingest._process_item(item)
        return json.loads(ingest._sqs.send_message.call_args.kwargs["MessageBody"])

    def _turn(self, message, creates_report):
        _ScriptedAgent.calls_report = creates_report
        return agent.lambda_handler(message, None)

    def _report_media(self):
        reports = [
            item for item in self.ddb.tables.get("reports", {}).values()
            if "description" in item
        ]
        self.assertEqual(len(reports), 1)
        return [value["S"] for value in reports[0].get("media", {}).get("L", [])]

    def test_photo_alone_then_text_attaches_photo(self):
        photo = self._inbound("wamid.P1", None, image=True)
        result = self._turn(photo, creates_report=False)
        self.assertTrue(result["ok"])
        self.assertIn(agent._PHOTO_WITHOUT_CAPTION_NOTE, _ScriptedAgent.prompts[0])

        followup = self._inbound("wamid.T1", "bache en Av. Universidad 100")
        self.assertEqual(followup["media"], None)
        self.assertTrue(self._turn(followup, creates_report=True)["ok"])

        self.assertEqual(self._report_media(), photo["media"])
        self.assertEqual(self.ddb.tables["pending-media"], {})

    def test_photo_with_caption_then_location_attaches_photo(self):
        photo = self._inbound("wamid.P2", "bache enorme", image=True)
        self.assertTrue(self._turn(photo, creates_report=False)["ok"])
        location = self._inbound("wamid.L2", "esta en Av. Universidad 100")
        self.assertTrue(self._turn(location, creates_report=True)["ok"])
        self.assertEqual(self._report_media(), photo["media"])

    def test_same_turn_report_does_not_duplicate_current_photo(self):
        photo = self._inbound("wamid.P3", "bache en Av. Universidad 100", image=True)
        self.assertTrue(self._turn(photo, creates_report=True)["ok"])
        self.assertEqual(self._report_media(), photo["media"])

    def test_pending_key_uses_only_user_hash(self):
        self._inbound("wamid.P4", None, image=True)
        stored = json.dumps(self.ddb.tables["pending-media"])
        self.assertIn(USER_HASH, stored)
        self.assertNotIn(SENDER, stored)

    def test_expired_pending_photo_is_not_attached(self):
        photo = self._inbound("wamid.P5", None, image=True)
        with mock.patch.object(ingest.time, "time", return_value=time.time() - 3601):
            self._inbound("wamid.P6", None, image=True)
        pending = next(iter(self.ddb.tables["pending-media"].values()))
        pending["expires_at"] = {"N": str(int(time.time()) + 3600)}
        later = self._inbound("wamid.T5", "bache en Av. Universidad 100")
        self.assertTrue(self._turn(later, creates_report=True)["ok"])
        self.assertEqual(self._report_media(), photo["media"])


if __name__ == "__main__":
    unittest.main()
