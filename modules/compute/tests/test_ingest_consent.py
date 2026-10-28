"""Ingest Lambda consent persistence (RF-38).

Covers the opt-in matcher `_is_consent_phrase`, the consent-write helper
`_grant_consent`, and the same-turn `consent_pending` flip when a brand-new
user's first message is an accepted opt-in phrase.

Run: python3 -m unittest discover -s modules/compute/tests
"""

import json
import os
import sys
import unittest
from unittest import mock

from botocore.exceptions import BotoCoreError, ClientError

os.environ.update({
    "INGEST_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/000000000000/q.fifo",
    "USERS_TABLE": "users",
    "AUDIT_TABLE": "audit",
    "MEDIA_BUCKET": "media",
    "MEDIA_STATE_MACHINE_ARN": "arn:aws:states:us-east-1:000000000000:stateMachine:media",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ingest"))

import handler  # noqa: E402

SENDER = "5215512345678"


def _sns_record(inner, mid="sns-1"):
    if isinstance(inner, dict):
        inner = json.dumps(inner)
    return {
        "EventSource": "aws:sns",
        "Sns": {"MessageId": mid, "Message": inner},
    }


def _queued_bodies():
    bodies = []
    for call in handler._sqs.send_message.call_args_list:
        bodies.append(json.loads(call.kwargs.get("MessageBody") or "{}"))
    return bodies


class ConsentPhraseMatcherTests(unittest.TestCase):
    def test_accepts_canonical_english_and_spanish(self):
        accepted = [
            "I ACCEPT",
            "i accept",
            "  I Accept  ",
            "I ACCEPT!",
            "YES I ACCEPT",
            "ACCEPT",
            "I AGREE",
            "YES",
            "SI ACEPTO",
            "SÍ ACEPTO",
            "Acepto",
            "SI",
            "Sí",
        ]
        for text in accepted:
            with self.subTest(text=text):
                self.assertTrue(handler._is_consent_phrase(text))

    def test_rejects_substrings_and_noise(self):
        rejected = [
            "I accept that it's broken",
            "no acepto",
            "yes but not really",
            "",
            None,
            "hola",
            "fuga en la calle",
        ]
        for text in rejected:
            with self.subTest(text=text):
                self.assertFalse(handler._is_consent_phrase(text))


class GrantConsentTests(unittest.TestCase):
    def setUp(self):
        handler._ddb = mock.MagicMock()

    def test_issues_update_item_with_consent_bool_true(self):
        handler._grant_consent(SENDER)
        handler._ddb.update_item.assert_called_once()
        kwargs = handler._ddb.update_item.call_args.kwargs
        self.assertEqual(kwargs["TableName"], handler.USERS_TABLE)
        self.assertEqual(kwargs["Key"], {"user_id": {"S": SENDER}})
        self.assertIn("SET consent = :true", kwargs["UpdateExpression"])
        self.assertEqual(kwargs["ExpressionAttributeValues"][":true"], {"BOOL": True})
        self.assertIn(":now", kwargs["ExpressionAttributeValues"])

    def test_swallows_client_error(self):
        handler._ddb.update_item.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "UpdateItem"
        )
        # Must not raise.
        handler._grant_consent(SENDER)

    def test_swallows_botocore_error(self):
        handler._ddb.update_item.side_effect = BotoCoreError()
        handler._grant_consent(SENDER)


class ConsentSameTurnFlipTests(unittest.TestCase):
    def setUp(self):
        handler._sqs = mock.MagicMock()
        handler._ddb = mock.MagicMock()
        handler._sfn = mock.MagicMock()
        handler._already_processed = lambda *a, **k: False
        handler._check_consent = lambda *a, **k: False
        handler._check_rate_limit = lambda *a, **k: False

    def test_first_accept_message_persists_consent_and_enqueues_not_pending(self):
        inner = {"from": SENDER, "text": "I ACCEPT", "message_id": "flat-accept", "type": "text"}
        event = {"Records": [_sns_record(inner, "sns-accept")]}
        with self.assertLogs(handler.logger, level="INFO") as cm:
            handler.lambda_handler(event, None)
        # _grant_consent runs an UpdateItem on the users table with consent true.
        update_calls = [
            c for c in handler._ddb.update_item.call_args_list
            if c.kwargs.get("ExpressionAttributeValues", {}).get(":true") == {"BOOL": True}
        ]
        self.assertEqual(len(update_calls), 1)
        bodies = _queued_bodies()
        self.assertEqual(len(bodies), 1)
        self.assertFalse(bodies[0]["consent_pending"])
        joined = " ".join(cm.output)
        self.assertIn("consent_granted", joined)
        self.assertNotIn(SENDER, joined)
        self.assertNotIn("I ACCEPT", joined)

    def test_non_consent_message_stays_pending(self):
        inner = {"from": SENDER, "text": "hola", "message_id": "flat-hola", "type": "text"}
        event = {"Records": [_sns_record(inner, "sns-hola")]}
        handler.lambda_handler(event, None)
        consent_updates = [
            c for c in handler._ddb.update_item.call_args_list
            if c.kwargs.get("ExpressionAttributeValues", {}).get(":true") == {"BOOL": True}
        ]
        self.assertEqual(consent_updates, [])
        bodies = _queued_bodies()
        self.assertEqual(len(bodies), 1)
        self.assertTrue(bodies[0]["consent_pending"])


if __name__ == "__main__":
    unittest.main()
