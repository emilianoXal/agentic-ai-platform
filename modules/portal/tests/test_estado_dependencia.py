"""Agency-sent status is visible only after the dependency mailer sends SES.

Run: python3 -m pytest -q modules/portal/tests/test_estado_dependencia.py
"""

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from botocore.exceptions import ClientError


ROOT = Path(__file__).resolve().parents[3]
MAILER = ROOT / "modules" / "compute" / "src" / "dependency_mailer" / "handler.py"
PORTAL = ROOT / "modules" / "portal" / "src" / "dashboard_api" / "handler.py"


class FakeDynamo:
    def __init__(self, incident):
        self.claims = set()
        self.audit = []
        self.incident = incident

    def put_item(self, TableName, Item, ConditionExpression=None):
        if ConditionExpression:
            key = (Item["entity_id"]["S"], Item["ts"]["S"])
            if key in self.claims:
                raise ClientError(
                    {"Error": {"Code": "ConditionalCheckFailedException"}},
                    "PutItem",
                )
            self.claims.add(key)
            return {}
        self.audit.append(Item)
        return {}

    def delete_item(self, TableName, Key):
        self.claims.discard((Key["entity_id"]["S"], Key["ts"]["S"]))
        return {}

    def get_item(self, TableName, Key, ConsistentRead=False):
        return {"Item": self.incident}

    def update_item(
        self,
        TableName,
        Key,
        UpdateExpression,
        ExpressionAttributeValues,
        ExpressionAttributeNames=None,
    ):
        names = ExpressionAttributeNames or {}
        set_part = UpdateExpression.split(" REMOVE ")[0].replace("SET ", "")
        for assignment in set_part.split(", "):
            attr, value = [p.strip() for p in assignment.split("=")]
            self.incident[names.get(attr, attr)] = ExpressionAttributeValues[value]
        return {}


class FakeSES:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def send_email(self, **kwargs):
        if self.error:
            raise self.error
        self.sent.append(kwargs)
        return {"MessageId": "ses-message-1"}


def _load(path, name, ddb, ses=None):
    env = {
        "INCIDENTS_TABLE": "incidents",
        "INCIDENTS_TABLE_NAME": "incidents",
        "REPORTS_TABLE_NAME": "reports",
        "AUDIT_TABLE": "audit",
        "AUDIT_TABLE_NAME": "audit",
        "USERS_TABLE_NAME": "users",
        "EVENT_BUS_NAME": "bus",
        "MAIL_FROM": "antonio.miguel@xaldigital.com",
        "DEPENDENCY_FALLBACK_EMAIL": "antonio.miguel+supervisor@xaldigital.com",
        "DEPENDENCY_EMAIL_MAP": json.dumps({"bacheo": "obras@example.com"}),
        "AWS_DEFAULT_REGION": "us-east-1",
    }
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    clients = {"dynamodb": ddb, "sesv2": ses or FakeSES(), "events": mock.Mock(), "scheduler": mock.Mock()}

    def client(service, *args, **kwargs):
        return clients.get(service, mock.Mock())

    sys.path.insert(0, str(path.parent))
    try:
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("boto3.client", side_effect=client):
            spec.loader.exec_module(module)
    finally:
        if str(path.parent) in sys.path:
            sys.path.remove(str(path.parent))
    module._ddb = ddb
    if ses is not None:
        module._ses = ses
    return module


def _routed_incident():
    return {
        "incident_id": {"S": "INC-42"},
        "status": {"S": "OPEN"},
        "category": {"S": "bacheo"},
        "neighborhood": {"S": "Centro"},
        "routed_to": {"S": "Obras Publicas"},
        "max_severity": {"S": "high"},
        "report_count": {"N": "1"},
        "geohash": {"S": "9g8t5s4"},
        "created_at": {"S": "2026-10-28T15:00:00+00:00"},
    }


def _creation_event():
    return {
        "id": "evt-create",
        "source": "urbanbot.agent",
        "detail-type": "StatusChanged",
        "detail": {"incident_id": "INC-42", "category": "bacheo"},
    }


class EstadoDependenciaTest(unittest.TestCase):
    def test_portal_stays_received_until_mailer_sends(self):
        ddb = FakeDynamo(_routed_incident())
        ses = FakeSES()
        mailer = _load(MAILER, "dependencia_mailer", ddb, ses)
        portal = _load(PORTAL, "dependencia_portal", ddb)

        before = portal.to_incident(ddb.incident)
        self.assertEqual(before["status"], "received")
        self.assertEqual(before["agencyName"], "Obras Publicas")
        route_line = portal._timeline_entry({
            "entity_id": {"S": "incident#INC-42"},
            "ts": {"S": "2026-10-28T15:01:00+00:00"},
            "kind": {"S": "route"},
            "dependency": {"S": "Obras Publicas"},
        })
        self.assertEqual(route_line["status"], None)
        self.assertIn("panel", route_line["text"])
        self.assertIn("pending", route_line["text"])

        result = mailer.lambda_handler(_creation_event(), None)

        self.assertTrue(result["sent"])
        self.assertEqual(result["message_id"], "ses-message-1")
        self.assertEqual(1, len(ses.sent))
        after = portal.to_incident(ddb.incident)
        self.assertEqual(after["status"], "sent_to_agency")
        self.assertTrue(ddb.incident["dependency_mail_sent_at"]["S"])
        mail_line = portal._timeline_entry(ddb.audit[-1])
        self.assertEqual(mail_line["status"], "sent_to_agency")
        self.assertEqual(mail_line["kind"], "status")

    def test_failed_mail_does_not_mark_sent_to_agency(self):
        ddb = FakeDynamo(_routed_incident())
        ses = FakeSES(error=RuntimeError("ses down"))
        mailer = _load(MAILER, "dependencia_mailer_fail", ddb, ses)
        portal = _load(PORTAL, "dependencia_portal_fail", ddb)

        with self.assertRaises(RuntimeError):
            mailer.lambda_handler(_creation_event(), None)

        self.assertEqual([], ses.sent)
        self.assertEqual(ddb.incident["status"]["S"], "OPEN")
        self.assertNotIn("dependency_mail_sent_at", ddb.incident)
        self.assertEqual([], ddb.audit)
        shown = portal.to_incident(ddb.incident)
        self.assertEqual(shown["status"], "received")


if __name__ == "__main__":
    unittest.main()
