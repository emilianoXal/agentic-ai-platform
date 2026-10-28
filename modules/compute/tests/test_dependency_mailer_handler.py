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
            "max_severity": {"S": "high"},
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
        agent_types = ("StatusChanged", "IncidentNearby")
        event = {
            "id": event_id,
            "source": "urbanbot.agent" if detail_type in agent_types else "urbanbot.dashboard",
            "detail-type": detail_type,
            "detail": {
                "incident_id": "INC-42",
                "category": "agua",
                "phone": "5215512345678",
                "name": "Ciudadana Ejemplo",
                "places": ["Casa", "Escuela"],
            },
        }
        if detail_type == "IncidentNearby":
            event["detail"]["status"] = "ESCALATED"
        return event

    def assert_safe_message(self, sent):
        serialized = json.dumps(sent, ensure_ascii=False)
        for expected in (
            "INC-42",
            "agua",
            "Centro",
            "Prioridad: high",
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

    def test_agent_escalation_sends_escalation_email(self):
        result = self.handler.lambda_handler(self.event("IncidentNearby", "evt-agent"), None)

        self.assertTrue(result["sent"])
        self.assertEqual(1, len(self.ses.sent))
        self.assertIn(
            "escalado",
            self.ses.sent[0]["Content"]["Simple"]["Subject"]["Data"],
        )
        self.assert_safe_message(self.ses.sent[0])

    def test_agent_nearby_without_escalation_is_ignored(self):
        event = self.event("IncidentNearby", "evt-nearby")
        event["detail"]["status"] = "OPEN"

        result = self.handler.lambda_handler(event, None)

        self.assertTrue(result["ignored"])
        self.assertEqual([], self.ses.sent)

    def test_agent_and_portal_escalation_send_one_email(self):
        agent = self.handler.lambda_handler(self.event("IncidentNearby", "evt-agent"), None)
        portal = self.handler.lambda_handler(self.event("IncidentEscalated", "evt-portal"), None)

        self.assertTrue(agent["sent"])
        self.assertTrue(portal["duplicate"])
        self.assertEqual(1, len(self.ses.sent))

    def test_location_falls_back_to_geohash(self):
        del self.ddb.incident["neighborhood"]
        self.ddb.incident["geohash"] = {"S": "9g3w81t"}

        self.handler.lambda_handler(self.event("StatusChanged", "evt-geo"), None)

        body = self.ses.sent[0]["Content"]["Simple"]["Body"]["Text"]["Data"]
        self.assertIn("Colonia: 9g3w81t", body)

    def test_failed_send_releases_claims_for_retry(self):
        event = self.event("IncidentEscalated", "evt-retry")
        with mock.patch.object(self.ses, "send_email", side_effect=RuntimeError("ses down")):
            with self.assertRaises(RuntimeError):
                self.handler.lambda_handler(event, None)

        result = self.handler.lambda_handler(event, None)

        self.assertTrue(result["sent"])
        self.assertEqual(1, len(self.ses.sent))


if __name__ == "__main__":
    unittest.main()
