"""WhatsApp location messages reach the agent and later create_report calls.

Run: python3 -m pytest -q modules/agent/tests/test_ubicacion.py
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


agent = _load("ubicacion_agent", ("agent", "src", "agent", "handler.py"))
create_report = _load("ubicacion_create_report", ("agent", "src", "create_report", "handler.py"))
ingest = _load("ubicacion_ingest", ("compute", "src", "ingest", "handler.py"))

SENDER = "5215599900001"
LAT = 20.58806
LNG = -100.38806
NAME = "Esquina Reforma"
ADDRESS = "Reforma y Universidad"
AWS_PHONE_ID = "976c72a700aac43eaf573ae050example"
META_PHONE_ID = "PNID"


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
        "message_timestamp": "2026-10-28T17:07:00Z",
        "messageId": message_id,
    }


def _sns_record(inner, mid="sns-1"):
    return {
        "EventSource": "aws:sns",
        "Sns": {"MessageId": mid, "Message": json.dumps(inner)},
    }


def _location_message(forwarded=False, latitude=LAT, longitude=LNG):
    message = {
        "from": SENDER,
        "id": "wamid.LOC1",
        "timestamp": "1793166000",
        "type": "location",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "name": NAME,
            "address": ADDRESS,
        },
    }
    if forwarded:
        message["context"] = {"forwarded": True, "frequently_forwarded": False}
    return message


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

    def get_item(self, **kwargs):
        return {}


class _Result:
    def __str__(self):
        return "Listo."

    message = None


class _ScriptedAgent:
    calls_report = False
    report_extra = {}
    prompts = []
    locations = []
    report_kwargs = []

    def __init__(self, **kwargs):
        self.messages = kwargs.get("messages", [])

    def __call__(self, prompt):
        _ScriptedAgent.prompts.append(prompt)
        _ScriptedAgent.locations.append(dict(agent._turn.get("location") or {}))
        if _ScriptedAgent.calls_report:
            _ScriptedAgent.report_kwargs.append(dict({
                "category": "bacheo",
                "geohash": "wrongcell",
                "description": (
                    "Patrulla estacionada bloquea el carril en la esquina"
                ),
            }, **_ScriptedAgent.report_extra))
            agent.create_report(**_ScriptedAgent.report_kwargs[-1])
        return _Result()


def _invoke_tool(FunctionName, InvocationType, Payload):
    result = create_report.lambda_handler(json.loads(Payload), None)
    return {"Payload": io.BytesIO(json.dumps(result).encode())}


class UbicacionWhatsAppTests(unittest.TestCase):
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
        _ScriptedAgent.locations = []
        _ScriptedAgent.report_kwargs = []
        _ScriptedAgent.calls_report = False
        _ScriptedAgent.report_extra = {}

    def _ingest(self, event):
        ingest._sqs.send_message.reset_mock()
        ingest.lambda_handler(event, None)
        bodies = []
        for call in ingest._sqs.send_message.call_args_list:
            bodies.append(json.loads(call.kwargs.get("MessageBody") or "{}"))
        return bodies

    def _location_event(self, forwarded=False, latitude=LAT, longitude=LNG):
        value = _meta(
            contacts=[{"profile": {"name": "Prueba"}, "wa_id": SENDER}],
            messages=[_location_message(
                forwarded=forwarded, latitude=latitude, longitude=longitude,
            )],
        )
        return {"Records": [_sns_record(_eum_envelope(_entry(value)))]}

    def _text_event(self, body):
        value = _meta(
            contacts=[{"profile": {"name": "Prueba"}, "wa_id": SENDER}],
            messages=[{
                "from": SENDER,
                "id": "wamid.TXT1",
                "timestamp": "1793166000",
                "type": "text",
                "text": {"body": body},
            }],
        )
        return {"Records": [_sns_record(_eum_envelope(_entry(value)))]}

    def _image_event(self, caption):
        value = _meta(
            contacts=[{"profile": {"name": "Prueba"}, "wa_id": SENDER}],
            messages=[{
                "from": SENDER,
                "id": "wamid.IMG1",
                "timestamp": "1793166100",
                "type": "image",
                "image": {
                    "mime_type": "image/jpeg",
                    "sha256": "abc",
                    "id": "530339869524171",
                    "caption": caption,
                },
            }],
        )
        return {"Records": [_sns_record(_eum_envelope(_entry(value)))]}

    def _reports(self):
        return [
            item for item in self.ddb.tables.get("reports", {}).values()
            if "category" in item
        ]

    def test_eum_location_payload_reaches_agent_with_lat_lng(self):
        bodies = self._ingest(self._location_event())
        self.assertEqual(len(bodies), 1)
        queued = bodies[0]
        self.assertEqual(queued["type"], "location")
        self.assertEqual(queued["location"]["lat"], LAT)
        self.assertEqual(queued["location"]["lng"], LNG)
        self.assertEqual(queued["location"]["name"], NAME)
        self.assertEqual(queued["location"]["address"], ADDRESS)
        self.assertIn("%.5f" % LAT, queued["text"])
        self.assertIn("%.5f" % LNG, queued["text"])
        self.assertIn("Shared location", queued["text"])

        _ScriptedAgent.calls_report = False
        result = agent.lambda_handler(queued, None)
        self.assertTrue(result["ok"])
        self.assertEqual(_ScriptedAgent.locations[0]["lat"], LAT)
        self.assertEqual(_ScriptedAgent.locations[0]["lng"], LNG)
        self.assertIn(str(LAT), _ScriptedAgent.prompts[0])
        self.assertIn(str(LNG), _ScriptedAgent.prompts[0])

    def test_forwarded_location_is_normalized_the_same(self):
        bodies = self._ingest(self._location_event(forwarded=True))
        self.assertEqual(bodies[0]["location"]["lat"], LAT)
        self.assertEqual(bodies[0]["location"]["lng"], LNG)
        result = agent.lambda_handler(bodies[0], None)
        self.assertTrue(result["ok"])
        self.assertEqual(_ScriptedAgent.locations[0]["lat"], LAT)

    def test_location_then_captioned_photo_creates_report_with_coordinates(self):
        loc_body = self._ingest(self._location_event())[0]
        self.assertTrue(agent.lambda_handler(loc_body, None)["ok"])
        self.assertEqual(self._reports(), [])

        photo_body = self._ingest(self._image_event(
            "Crea un reporte para Patrulla estacionada bloquea el carril en la esquina",
        ))[0]
        self.assertIsNone(photo_body.get("location"))
        _ScriptedAgent.calls_report = True
        result = agent.lambda_handler(photo_body, None)
        self.assertTrue(result["ok"])

        reports = self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(float(reports[0]["lat"]["S"]), LAT)
        self.assertEqual(float(reports[0]["lng"]["S"]), LNG)
        self.assertEqual(
            reports[0]["geohash"]["S"],
            agent._encode_geohash(LAT, LNG),
        )
        self.assertEqual(_ScriptedAgent.locations[-1]["lat"], LAT)
        self.assertEqual(_ScriptedAgent.locations[-1]["lng"], LNG)
        history = sorted(
            self.ddb.tables.get("history", {}).values(),
            key=lambda item: item["ts"]["S"],
        )
        self.assertEqual([bool(item.get("location")) for item in history], [True, False])
        self.assertTrue(history[-1]["report_created"]["BOOL"])

    def test_explicit_coordinates_override_pending_location(self):
        loc_body = self._ingest(self._location_event())[0]
        self.assertTrue(agent.lambda_handler(loc_body, None)["ok"])
        self.assertIn("shared this location 0 minutes ago", _ScriptedAgent.prompts[0])

        new_lat, new_lng = 20.61, -100.41
        _ScriptedAgent.calls_report = True
        _ScriptedAgent.report_extra = {
            "lat": new_lat, "lng": new_lng,
            "geohash": agent._encode_geohash(new_lat, new_lng),
        }
        body = self._ingest(self._text_event("otro reporte: bache en 20.61,-100.41"))[0]
        self.assertTrue(agent.lambda_handler(body, None)["ok"])

        reports = self._reports()
        self.assertEqual(len(reports), 1)
        self.assertEqual(float(reports[0]["lat"]["S"]), new_lat)
        self.assertEqual(float(reports[0]["lng"]["S"]), new_lng)
        self.assertEqual(reports[0]["geohash"]["S"], agent._encode_geohash(new_lat, new_lng))

    def test_second_report_does_not_reuse_consumed_location(self):
        loc_body = self._ingest(self._location_event())[0]
        self.assertTrue(agent.lambda_handler(loc_body, None)["ok"])
        _ScriptedAgent.calls_report = True
        photo_body = self._ingest(self._image_event("Crea un reporte de bache"))[0]
        self.assertTrue(agent.lambda_handler(photo_body, None)["ok"])

        body = self._ingest(self._text_event("otro reporte: luminaria apagada"))[0]
        self.assertTrue(agent.lambda_handler(body, None)["ok"])

        self.assertEqual(_ScriptedAgent.locations[-1], {})
        self.assertNotIn("shared this location", _ScriptedAgent.prompts[-1])
        reports = sorted(self._reports(), key=lambda item: "lat" in item)
        self.assertEqual(len(reports), 2)
        self.assertNotIn("lat", reports[0])
        self.assertEqual(reports[0]["geohash"]["S"], "wrongcell")
        self.assertEqual(float(reports[1]["lat"]["S"]), LAT)

    def test_pending_location_expires_after_thirty_minutes(self):
        loc_body = self._ingest(self._location_event())[0]
        self.assertTrue(agent.lambda_handler(loc_body, None)["ok"])
        stale = agent.datetime.fromtimestamp(
            agent.time.time() - 31 * 60, agent.timezone.utc,
        ).isoformat()
        for item in self.ddb.tables["history"].values():
            item["ts"]["S"] = stale + "#" + item["ts"]["S"].split("#")[1]

        _ScriptedAgent.calls_report = True
        body = self._ingest(self._text_event("reporte: bache"))[0]
        self.assertTrue(agent.lambda_handler(body, None)["ok"])

        self.assertEqual(_ScriptedAgent.locations[-1], {})
        reports = self._reports()
        self.assertEqual(len(reports), 1)
        self.assertNotIn("lat", reports[0])

    def test_text_without_location_stays_plain_text(self):
        bodies = self._ingest(self._text_event("hola"))
        self.assertEqual(len(bodies), 1)
        queued = bodies[0]
        self.assertEqual(queued["text"], "hola")
        self.assertEqual(queued["type"], "text")
        self.assertNotIn("location", queued)

        _ScriptedAgent.calls_report = True
        result = agent.lambda_handler(queued, None)
        self.assertTrue(result["ok"])
        self.assertEqual(_ScriptedAgent.locations[0], {})
        self.assertNotIn("shared this location", _ScriptedAgent.prompts[0])
        reports = self._reports()
        self.assertEqual(len(reports), 1)
        self.assertNotIn("lat", reports[0])
        self.assertNotIn("lng", reports[0])
        self.assertEqual(reports[0]["geohash"]["S"], "wrongcell")


if __name__ == "__main__":
    unittest.main()
