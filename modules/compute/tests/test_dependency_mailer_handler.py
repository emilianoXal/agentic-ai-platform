import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from botocore.exceptions import ClientError


HANDLER = Path(__file__).parents[1] / "src" / "dependency_mailer" / "handler.py"


class FakeDynamoDB:
    def __init__(self):
        self.claims = set()
        self.incident = {
            "incident_id": {"S": "INC-42"},
            "category": {"S": "agua"},
            "neighborhood": {"S": "Centro"},
            "priority": {"N": "9"},
            "report_count": {"N": "7"},
        }

    def put_item(self, TableName, Item, ConditionExpression):
        key = (Item["entity_id"]["S"], Item["ts"]["S"])
        if key in self.claims:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}},
                "PutItem",
            )
        self.claims.add(key)
        return {}

    def delete_item(self, TableName, Key):
        self.claims.discard((Key["entity_id"]["S"], Key["ts"]["S"]))
        return {}

    def get_item(self, TableName, Key, ConsistentRead):
        return {"Item": self.incident}


class FakeSES:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "message-1"}


class DependencyMailerTest(unittest.TestCase):
    def setUp(self):
        self.ddb = FakeDynamoDB()
        self.ses = FakeSES()
        env = {
            "INCIDENTS_TABLE": "incidents",
            "AUDIT_TABLE": "audit",
            "MAIL_FROM": "antonio.miguel@xaldigital.com",
            "DEPENDENCY_FALLBACK_EMAIL": "antonio.miguel+supervisor@xaldigital.com",
            "DEPENDENCY_EMAIL_MAP": json.dumps({
                "agua": "antonio.miguel+agua@xaldigital.com",
            }),
        }
        spec = importlib.util.spec_from_file_location("dependency_mailer_test", HANDLER)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch(
            "boto3.client",
            side_effect=lambda service: self.ddb if service == "dynamodb" else self.ses,
        ):
            spec.loader.exec_module(module)
        self.handler = module

    def event(self, detail_type, event_id):
        return {
            "id": event_id,
            "source": "urbanbot.agent" if detail_type == "StatusChanged" else "urbanbot.dashboard",
            "detail-type": detail_type,
            "detail": {
                "incident_id": "INC-42",
                "category": "agua",
                "phone": "5215512345678",
                "name": "Ciudadana Ejemplo",
                "places": ["Casa", "Escuela"],
            },
        }

    def assert_safe_message(self, sent):
        serialized = json.dumps(sent, ensure_ascii=False)
        for expected in (
            "INC-42",
            "agua",
            "Centro",
            "9",
            "7",
            "https://main.d1taemvhj3go47.amplifyapp.com/incidents",
        ):
            self.assertIn(expected, serialized)
        for sensitive in ("5215512345678", "Ciudadana Ejemplo", "Casa", "Escuela"):
            self.assertNotIn(sensitive, serialized)

    def test_creation_sends_safe_incident_email(self):
        result = self.handler.lambda_handler(self.event("StatusChanged", "evt-create"), None)

        self.assertTrue(result["sent"])
        self.assertEqual(1, len(self.ses.sent))
        self.assertEqual(
            ["antonio.miguel+agua@xaldigital.com"],
            self.ses.sent[0]["Destination"]["ToAddresses"],
        )
        self.assert_safe_message(self.ses.sent[0])

    def test_escalation_sends_safe_incident_email(self):
        result = self.handler.lambda_handler(self.event("IncidentEscalated", "evt-escalate"), None)

        self.assertTrue(result["sent"])
        self.assertEqual(1, len(self.ses.sent))
        self.assertIn(
            "escalado",
            self.ses.sent[0]["Content"]["Simple"]["Subject"]["Data"],
        )
        self.assert_safe_message(self.ses.sent[0])

    def test_repeated_event_does_not_send_again(self):
        event = self.event("IncidentEscalated", "evt-repeat")

        first = self.handler.lambda_handler(event, None)
        second = self.handler.lambda_handler(event, None)

        self.assertTrue(first["sent"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(1, len(self.ses.sent))


if __name__ == "__main__":
    unittest.main()
