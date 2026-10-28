"""Ingest Lambda: AWS End User Messaging Social WhatsApp events.

The SNS body follows the documented EUM envelope (context + whatsAppWebhookEntry
JSON string). See:
https://docs.aws.amazon.com/social-messaging/latest/userguide/managing-event-destination-dlrs.html

Inner webhook fields follow Meta's messages webhook:
https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components

Run: python3 -m unittest discover -s modules/compute/tests
"""

import json
import logging
import os
import sys
import unittest
from unittest import mock

os.environ.update({
    "INGEST_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/000000000000/q.fifo",
    "USERS_TABLE": "users",
    "AUDIT_TABLE": "audit",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ingest"))

import handler  # noqa: E402

SENDER = "5215512345678"
TEXT_HOLA = "hola"
WAMID_1 = "wamid.TEST1"
WAMID_2 = "wamid.TEST2"
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
        "message_timestamp": "2026-10-28T05:38:55Z",
        "messageId": message_id,
    }


def _sns_record(inner, mid="sns-1"):
    if isinstance(inner, dict):
        inner = json.dumps(inner)
    return {
        "EventSource": "aws:sns",
        "Sns": {"MessageId": mid, "Message": inner},
    }


def _text_value(*bodies):
    messages = []
    for i, body in enumerate(bodies, start=1):
        messages.append({
            "from": SENDER,
            "id": "wamid.TEST%s" % i,
            "timestamp": "1793166000",
            "type": "text",
            "text": {"body": body},
        })
    return _meta(
        contacts=[{"profile": {"name": "Prueba"}, "wa_id": SENDER}],
        messages=messages,
    )


def _status_value(status="delivered"):
    return _meta(statuses=[{
        "id": "wamid.OUT1",
        "status": status,
        "timestamp": "1793166001",
        "recipient_id": SENDER,
    }])


def _queued_bodies():
    bodies = []
    for call in handler._sqs.send_message.call_args_list:
        bodies.append(json.loads(call.kwargs.get("MessageBody") or "{}"))
    for call in handler._sqs.send_message_batch.call_args_list:
        for entry in call.kwargs.get("Entries") or []:
            bodies.append(json.loads(entry.get("MessageBody") or "{}"))
    return bodies


class IngestEumTests(unittest.TestCase):
    def setUp(self):
        handler._sqs = mock.MagicMock()
        handler._ddb = mock.MagicMock()
        handler._already_processed = lambda *a, **k: False
        handler._check_consent = lambda *a, **k: True
        handler._check_rate_limit = lambda *a, **k: False

    def test_eum_text_enqueues_sender_text_and_origination(self):
        event = {"Records": [_sns_record(_eum_envelope(_entry(_text_value(TEXT_HOLA))))]}
        handler.lambda_handler(event, None)
        bodies = _queued_bodies()
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0]["user_id"], SENDER)
        self.assertEqual(bodies[0]["text"], TEXT_HOLA)
        self.assertEqual(bodies[0]["message_id"], WAMID_1)
        self.assertEqual(bodies[0]["type"], "text")
        self.assertEqual(bodies[0]["origination_phone_number_id"], AWS_PHONE_ID)

    def test_eum_status_is_not_enqueued(self):
        event = {"Records": [_sns_record(_eum_envelope(_entry(_status_value()), "sns-2"), "sns-2")]}
        with self.assertLogs(handler.logger, level="INFO") as cm:
            handler.lambda_handler(event, None)
        self.assertEqual(_queued_bodies(), [])
        joined = " ".join(cm.output)
        self.assertIn("whatsapp_status", joined)
        self.assertIn("delivered", joined)
        self.assertNotIn(SENDER, joined)

    def test_eum_multiple_messages_each_enqueued(self):
        value = _text_value("hola", "fuga en la calle")
        event = {"Records": [_sns_record(_eum_envelope(_entry(value)))]}
        handler.lambda_handler(event, None)
        bodies = _queued_bodies()
        self.assertEqual(len(bodies), 2)
        self.assertEqual([b["text"] for b in bodies], ["hola", "fuga en la calle"])
        self.assertEqual([b["message_id"] for b in bodies], [WAMID_1, WAMID_2])
        self.assertEqual({b["user_id"] for b in bodies}, {SENDER})

    def test_eum_malformed_inner_json_is_not_enqueued(self):
        envelope = _eum_envelope(_entry(_text_value(TEXT_HOLA)))
        envelope["whatsAppWebhookEntry"] = "{not-json"
        event = {"Records": [_sns_record(envelope)]}
        with self.assertLogs(handler.logger, level="WARNING") as cm:
            result = handler.lambda_handler(event, None)
        self.assertEqual(_queued_bodies(), [])
        self.assertEqual(result.get("enqueued", 0), 0)
        self.assertIn("webhook_parse_failed", " ".join(cm.output))

    def test_eum_media_keeps_media_id(self):
        value = _meta(
            contacts=[{"profile": {"name": "Prueba"}, "wa_id": SENDER}],
            messages=[{
                "from": SENDER,
                "id": "wamid.IMG1",
                "timestamp": "1723506230",
                "type": "image",
                "image": {
                    "mime_type": "image/jpeg",
                    "sha256": "abc",
                    "id": "530339869524171",
                },
            }],
        )
        event = {"Records": [_sns_record(_eum_envelope(_entry(value)))]}
        handler.lambda_handler(event, None)
        bodies = _queued_bodies()
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0]["type"], "image")
        self.assertEqual(bodies[0]["media"]["id"], "530339869524171")
        self.assertEqual(bodies[0]["user_id"], SENDER)

    def test_flat_json_still_enqueues(self):
        inner = {"from": SENDER, "text": TEXT_HOLA, "message_id": "flat-1", "type": "text"}
        event = {"Records": [_sns_record(inner, "sns-flat")]}
        handler.lambda_handler(event, None)
        bodies = _queued_bodies()
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0]["user_id"], SENDER)
        self.assertEqual(bodies[0]["text"], TEXT_HOLA)
        self.assertEqual(bodies[0]["message_id"], "flat-1")

    def test_enqueued_logs_mask_phone_and_omit_text(self):
        event = {"Records": [_sns_record(_eum_envelope(_entry(_text_value(TEXT_HOLA))))]}
        with self.assertLogs(handler.logger, level="INFO") as cm:
            handler.lambda_handler(event, None)
        joined = " ".join(cm.output)
        self.assertNotIn(SENDER, joined)
        self.assertNotIn(TEXT_HOLA, joined)
        self.assertIn("****5678", joined)
        self.assertIn("text_len", joined)


if __name__ == "__main__":
    unittest.main()
