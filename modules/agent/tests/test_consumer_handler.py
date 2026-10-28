"""Consumer Lambda: inbound SQS body including origination phone id.

Run: python3 -m unittest discover -s modules/agent/tests
"""

import json
import os
import sys
import unittest
from unittest import mock

os.environ.update({
    "AUDIT_TABLE": "audit",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AGENTCORE_RUNTIME_ENABLED": "false",
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "consumer"))

import handler  # noqa: E402

SENDER = "5215512345678"
TEXT_HOLA = "hola"
ORIGIN = "976c72a700aac43eaf573ae050example"


class ConsumerIngestBodyTests(unittest.TestCase):
    def setUp(self):
        handler._ddb = mock.MagicMock()

    def test_origination_phone_number_id_is_logged_without_pii(self):
        body = {
            "user_id": SENDER,
            "message_id": "wamid.TEST1",
            "type": "text",
            "text": TEXT_HOLA,
            "origination_phone_number_id": ORIGIN,
            "consent_pending": False,
            "rate_limited": False,
        }
        event = {"Records": [{"messageId": "sqs-1", "body": json.dumps(body)}]}
        with self.assertLogs(handler.logger, level="INFO") as cm:
            result = handler.lambda_handler(event, None)
        self.assertEqual(result["batchItemFailures"], [])
        joined = " ".join(cm.output)
        self.assertIn(ORIGIN, joined)
        self.assertNotIn(SENDER, joined)
        self.assertNotIn(TEXT_HOLA, joined)
        handler._ddb.put_item.assert_called_once()


if __name__ == "__main__":
    unittest.main()
