"""Pending photo is attached when the report is created on a later turn.

Run: python3 -m pytest -q modules/agent/tests/test_foto_pendiente.py
"""

import hashlib
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
    "CONVERSATION_HISTORY_TABLE": "history",
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


agent = _load("foto_pendiente_agent", ("agent", "src", "agent", "handler.py"))
create_report = _load("foto_pendiente_create_report", ("agent", "src", "create_report", "handler.py"))
ingest = _load("foto_pendiente_ingest", ("compute", "src", "ingest", "handler.py"))

SENDER = "5215599900001"
LAT = 20.58806
LNG = -100.38806
CAPTION = "Parked patrol car blocking the lane at the corner"
AWS_PHONE_ID = "976c72a700aac43eaf573ae050example"
META_PHONE_ID = "PNID"
PHOTO_ID = "wamid.FOTO1"


def _sanitized_key(message_id):
    return "sanitized/" + hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:32]


def _entry(value):
    return {"id": "WABA", "changes": [{"field": "messages", "value": value}]}


def _meta(**extra):
    body = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "13192716611",
            "phone_number_id": META_PHONE_ID,
        },
    }
    body.update(extra)
    return body


def _eum_envelope(entry, message_id="sns-1"):
    return {
        "context": {
            "MetaWabaIds": [{
                "wabaId": "WABA",
                "arn": "arn:aws:social-messaging:us-east-1:000000000000:waba/x",
            }],
            "MetaPhoneNumberIds": [{
                "metaPhoneNumberId": META_PHONE_ID,
                "arn": (
                    "arn:aws:social-messaging:us-east-1:000000000000:"
                    "phone-number-id/" + AWS_PHONE_ID
                ),
            }],
        },
        "whatsAppWebhookEntry": json.dumps(entry),
        "aws_account_id": "000000000000",
        "message_timestamp": "2026-10-28T17:48:00Z",
        "messageId": message_id,
    }


def _sns_record(inner, mid="sns-1"):
    return {
        "EventSource": "aws:sns",
        "Sns": {"MessageId": mid, "Message": json.dumps(inner)},
    }


class FakeDynamo:
    def __init__(self):
        self.tables = {}

    def _table(self, name):
        return self.tables.setdefault(name, {})

    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeValues,
                    ExpressionAttributeNames=None, **kwargs):
        key = json.dumps(Key, sort_keys=True)
        item = self._table(TableName).setdefault(key, dict(Key))
        if TableName == "pending-media" and ExpressionAttributeNames:
            item[ExpressionAttributeNames["#key"]] = ExpressionAttributeValues[":exp"]
            item["expires_at"] = ExpressionAttributeValues[":exp"]
        return {}

    def delete_item(self, TableName, Key, ReturnValues=None, **kwargs):
        item = self._table(TableName).pop(json.dumps(Key, sort_keys=True), None)
        return {"Attributes": item} if item else {}

    def put_item(self, TableName, Item, **kwargs):
        self._table(TableName)[json.dumps(Item, sort_keys=True)] = Item
        return {}

    def query(self, TableName, **kwargs):
        values = list(self._table(TableName).values())
        citizen = (kwargs.get("ExpressionAttributeValues") or {}).get(":c", {}).get("S")
        if TableName == "history" and citizen:
            items = [i for i in values if i.get("citizen_id", {}).get("S") == citizen]
            items.sort(key=lambda i: i.get("ts", {}).get("S", ""), reverse=True)
            limit = kwargs.get("Limit")
            if limit:
                items = items[:limit]
            return {"Items": items}
        return {"Items": []}


class _Result:
    def __str__(self):
        return "Listo."

    message = None


class _ScriptedAgent:
    calls_report = False
    prompts = []

    def __init__(self, **kwargs):
        self.messages = kwargs.get("messages", [])

    def __call__(self, prompt):
        _ScriptedAgent.prompts.append(prompt)
        if _ScriptedAgent.calls_report:
            agent.create_report(
                category="seguridad",
                geohash="wrongcell",
                description=CAPTION,
            )
        return _Result()


def _invoke_tool(FunctionName, InvocationType, Payload):
    result = create_report.lambda_handler(json.loads(Payload), None)
    return {"Payload": io.BytesIO(json.dumps(result).encode())}


class FotoPendienteTests(unittest.TestCase):
    def setUp(self):
        self.ddb = FakeDynamo()
        ingest._ddb = self.ddb
        create_report._ddb = self.ddb
        ingest._sqs = mock.MagicMock()
        ingest._sfn = mock.MagicMock()
        ingest._already_processed = lambda *a, **k: False
        ingest._check_consent = lambda *a, **k: True
        ingest._check_rate_limit = lambda *a, **k: False
        agent._ddb = self.ddb
        agent.Agent = _ScriptedAgent
        agent.BedrockModel = mock.MagicMock()
        agent._lambda = mock.MagicMock()
        agent._lambda.invoke.side_effect = _invoke_tool
        agent.TOOL_CREATE_REPORT_FN = "create-report"
        agent.TOOL_FOLLOW_UP_FN = ""
        agent.CONVERSATION_HISTORY_TABLE = "history"
        agent._citizen_key = lambda user_id: "ck-" + str(user_id)
        _ScriptedAgent.prompts = []
        _ScriptedAgent.calls_report = False

    def _ingest(self, event):
        ingest._sqs.send_message.reset_mock()
        ingest.lambda_handler(event, None)
        return json.loads(ingest._sqs.send_message.call_args.kwargs["MessageBody"])

    def _image_event(self, caption, message_id=PHOTO_ID, forwarded=True):
        image = {
            "mime_type": "image/jpeg",
            "sha256": "abc",
            "id": "media-" + message_id,
        }
        if caption is not None:
            image["caption"] = caption
        message = {
            "from": SENDER,
            "id": message_id,
            "timestamp": "1793166000",
            "type": "image",
            "image": image,
        }
        if forwarded:
            message["context"] = {"forwarded": True, "frequently_forwarded": False}
        value = _meta(
            contacts=[{"profile": {"name": "Prueba"}, "wa_id": SENDER}],
            messages=[message],
        )
        return {"Records": [_sns_record(_eum_envelope(_entry(value), message_id), message_id)]}

    def _location_event(self, message_id="wamid.LOC1"):
        message = {
            "from": SENDER,
            "id": message_id,
            "timestamp": "1793166060",
            "type": "location",
            "location": {
                "latitude": LAT,
                "longitude": LNG,
                "name": "Esquina",
                "address": "Reforma y Universidad",
            },
        }
        value = _meta(
            contacts=[{"profile": {"name": "Prueba"}, "wa_id": SENDER}],
            messages=[message],
        )
        return {"Records": [_sns_record(_eum_envelope(_entry(value), message_id), message_id)]}

    def _text_event(self, body, message_id="wamid.TXT1"):
        message = {
            "from": SENDER,
            "id": message_id,
            "timestamp": "1793166060",
            "type": "text",
            "text": {"body": body},
        }
        value = _meta(
            contacts=[{"profile": {"name": "Prueba"}, "wa_id": SENDER}],
            messages=[message],
        )
        return {"Records": [_sns_record(_eum_envelope(_entry(value), message_id), message_id)]}

    def _reports(self):
        return [
            item for item in self.ddb.tables.get("reports", {}).values()
            if "category" in item
        ]

    def _report_media(self, report):
        return [value["S"] for value in report.get("media", {}).get("L", [])]

    def _incidents(self):
        return list(self.ddb.tables.get("incidents", {}).values())

    def _photo_then_location(self, caption=CAPTION, wipe_pending=False):
        photo = self._ingest(self._image_event(caption))
        self.assertTrue(ingest._sfn.start_execution.called)
        self.assertTrue(agent.lambda_handler(photo, None)["ok"])
        if wipe_pending:
            self.ddb.tables["pending-media"] = {}
        _ScriptedAgent.calls_report = True
        location = self._ingest(self._location_event())
        self.assertTrue(agent.lambda_handler(location, None)["ok"])
        reports = self._reports()
        self.assertEqual(len(reports), 1)
        return photo, reports[0]

    def test_captioned_photo_then_location_attaches_sanitized_key(self):
        photo, report = self._photo_then_location()
        self.assertEqual(self._report_media(report), photo["media"])
        self.assertEqual(photo["media"], [_sanitized_key(PHOTO_ID)])
        self.assertEqual(self._incidents()[0]["photo_count"]["N"], "1")
        self.assertEqual(self.ddb.tables.get("pending-media", {}), {})

    def test_captioned_photo_survives_pending_table_gap_via_history(self):
        photo, report = self._photo_then_location(wipe_pending=True)
        self.assertEqual(self._report_media(report), photo["media"])
        self.assertEqual(self._incidents()[0]["photo_count"]["N"], "1")

    def test_captionless_photo_then_text_attaches_sanitized_key(self):
        photo = self._ingest(self._image_event(None, message_id="wamid.FOTO2"))
        self.assertTrue(agent.lambda_handler(photo, None)["ok"])
        self.ddb.tables["pending-media"] = {}
        _ScriptedAgent.calls_report = True
        followup = self._ingest(self._text_event(CAPTION))
        self.assertEqual(followup.get("media"), None)
        self.assertTrue(agent.lambda_handler(followup, None)["ok"])
        reports = self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(self._report_media(reports[0]), photo["media"])
        self.assertEqual(self._incidents()[0]["photo_count"]["N"], "1")

    def test_unfinished_sanitize_still_attaches_the_key(self):
        photo, report = self._photo_then_location()
        self.assertEqual(self._report_media(report), photo["media"])
        ingest._sfn.start_execution.assert_called()
        payload = json.loads(ingest._sfn.start_execution.call_args.kwargs["input"])
        self.assertEqual(payload["sanitizedKey"], photo["media"][0])
        self.assertNotIn("s3", self.ddb.tables)

    def test_later_unrelated_report_does_not_inherit_the_photo(self):
        self._photo_then_location()
        _ScriptedAgent.calls_report = True
        later = self._ingest(self._text_event("otro reporte: luminaria apagada", "wamid.TXT2"))
        self.assertTrue(agent.lambda_handler(later, None)["ok"])
        reports = sorted(self._reports(), key=lambda item: item["created_at"]["S"])
        self.assertEqual(len(reports), 2)
        self.assertEqual(self._report_media(reports[0]), [_sanitized_key(PHOTO_ID)])
        self.assertEqual(self._report_media(reports[1]), [])


if __name__ == "__main__":
    unittest.main()
