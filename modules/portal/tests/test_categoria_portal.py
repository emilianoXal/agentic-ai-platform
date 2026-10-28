"""The portal says sent to agency only with a dependency mail and a dependency.

Run: python3 -m pytest -q modules/portal/tests/test_categoria_portal.py
"""

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PORTAL = ROOT / "modules" / "portal" / "src" / "dashboard_api" / "handler.py"
MAILER = ROOT / "modules" / "compute" / "src" / "dependency_mailer" / "handler.py"


def _load():
    env = {
        "INCIDENTS_TABLE_NAME": "incidents",
        "REPORTS_TABLE_NAME": "reports",
        "AUDIT_TABLE_NAME": "audit",
        "USERS_TABLE_NAME": "users",
        "EVENT_BUS_NAME": "bus",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
    }
    spec = importlib.util.spec_from_file_location("categoria_portal", PORTAL)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PORTAL.parent))
    try:
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("boto3.client", return_value=mock.Mock()):
            spec.loader.exec_module(module)
    finally:
        if str(PORTAL.parent) in sys.path:
            sys.path.remove(str(PORTAL.parent))
    return module


portal = _load()


def _load_mailer():
    env = {
        "INCIDENTS_TABLE": "incidents",
        "AUDIT_TABLE": "audit",
        "MAIL_FROM": "sender@example.com",
        "DEPENDENCY_FALLBACK_EMAIL": "supervisor@example.com",
        "DEPENDENCY_EMAIL_MAP": json.dumps({"bacheo": "obras@example.com"}),
        "AWS_DEFAULT_REGION": "us-east-1",
    }
    spec = importlib.util.spec_from_file_location("categoria_mailer", MAILER)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, env, clear=False), mock.patch("boto3.client", return_value=mock.Mock()):
        spec.loader.exec_module(module)
    return module


mailer = _load_mailer()


class FakeSES:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "ses-message-1"}


class FakeDynamo:
    def __init__(self, item):
        self.item = item
        self.updates = []
        self.audit = []

    def get_item(self, TableName, Key, ConsistentRead=False):
        return {"Item": dict(self.item)}

    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeValues,
                    ExpressionAttributeNames=None, ConditionExpression=None):
        self.updates.append(UpdateExpression)
        names = ExpressionAttributeNames or {}
        for assignment in UpdateExpression.split(" REMOVE ")[0].replace("SET ", "").split(", "):
            attr, value = [part.strip() for part in assignment.split("=")]
            self.item[names.get(attr, attr)] = ExpressionAttributeValues[value]

    def put_item(self, TableName, Item, ConditionExpression=None):
        if not ConditionExpression:
            self.audit.append(Item)

    def delete_item(self, TableName, Key):
        return {}

    def batch_get_item(self, RequestItems):
        return {"Responses": {}}

    def query(self, **_):
        return {"Items": []}


class FakeEvents:
    def __init__(self):
        self.entries = []

    def put_events(self, Entries):
        self.entries.extend(Entries)


def _supervisor_sets(item, status, dependency=None):
    ddb, events = FakeDynamo(item), FakeEvents()
    with mock.patch.object(portal, "_ddb", ddb), mock.patch.object(portal, "_events", events):
        result = portal.update_status(
            {"arguments": {"id": "inc-1", "status": status, "dependency": dependency}},
            {"name": "Supervisor", "groups": {"official"}, "agency_id": None},
        )
    return result["incident"], ddb, events


def _open_item(**extra):
    item = {
        "incident_id": {"S": "inc-1"},
        "status": {"S": "OPEN"},
        "category": {"S": "bacheo"},
        "geohash": {"S": "9g3qrbc"},
        "created_at": {"S": "2026-10-28T00:00:00+00:00"},
    }
    item.update(extra)
    return item


class PortalCategoriaTests(unittest.TestCase):
    def test_sent_to_agency_needs_mail_and_dependency(self):
        mailed = _open_item(dependency_mail_sent_at={"S": "2026-10-28T00:01:00+00:00"})
        without_dependency = portal.to_incident(mailed)
        self.assertEqual(without_dependency["status"], "received")
        self.assertIsNone(without_dependency["agencyName"])

        mailed["routed_to"] = {"S": "Obras Publicas"}
        shown = portal.to_incident(mailed)
        self.assertEqual(shown["status"], "sent_to_agency")
        self.assertEqual(shown["agencyName"], "Obras Publicas")

    def test_supervisor_fallback_stays_received_and_says_so(self):
        shown = portal.to_incident(_open_item(
            category={"S": "otro"},
            routed_to={"S": "Supervisor municipal"},
        ))
        self.assertEqual(shown["status"], "received")
        self.assertEqual(shown["category"], "otro")
        self.assertEqual(shown["agencyName"], "Supervisor municipal")
        line = portal._timeline_entry({
            "kind": {"S": "supervisor_mail_sent"},
            "entity_id": {"S": "incident#inc-1"},
            "ts": {"S": "2026-10-28T00:02:00+00:00"},
        })
        self.assertEqual(line["text"], "Email sent to the supervisor")
        self.assertIsNone(line["status"])
        self.assertNotEqual(shown["status"], "sent_to_agency")


    def test_stored_sent_to_agency_reads_sent_only_with_mail_and_dependency(self):
        mailed = {"S": "2026-10-28T00:01:00+00:00"}
        routed = {"S": "Obras Publicas"}
        cases = (
            ({"dependency_mail_sent_at": mailed, "routed_to": routed}, "sent_to_agency"),
            ({"routed_to": routed}, "pending_send"),
            ({"dependency_mail_sent_at": mailed}, "pending_send"),
            ({}, "pending_send"),
        )
        for extra, expected in cases:
            stored = _open_item(status={"S": "sent_to_agency"}, **extra)
            ddb = FakeDynamo(stored)
            with mock.patch.object(portal, "_ddb", ddb):
                shown = portal._detail(portal._get_item("inc-1"))
            self.assertEqual(shown["status"], expected, extra)
            self.assertEqual(ddb.updates, [])
            self.assertEqual(ddb.audit, [])
            self.assertEqual(ddb.item["status"]["S"], "sent_to_agency")
        self.assertNotIn("pending_send", portal.STATUS_CODES)

    def test_send_without_a_known_dependency_is_rejected_and_sends_no_mail(self):
        for dependency in (None, "", "Parques", "Supervisor municipal"):
            with self.assertRaises(portal.DashboardError) as ctx:
                _supervisor_sets(_open_item(), "sent_to_agency", dependency)
            self.assertEqual(ctx.exception.code, "invalid_input")
        ses = FakeSES()
        with mock.patch.object(mailer, "_ses", ses):
            ignored = mailer.lambda_handler({
                "id": "evt-none", "source": "urbanbot.dashboard", "detail-type": "StatusChanged",
                "detail": {"incident_id": "inc-1", "status": "in_progress"},
            }, None)
        self.assertTrue(ignored["ignored"])
        self.assertEqual(ses.sent, [])

    def test_send_with_a_chosen_dependency_mails_it_then_reads_sent(self):
        incident, ddb, events = _supervisor_sets(
            _open_item(category={"S": "otro"}, report_ids={"L": [{"S": "rep-1"}]}),
            "sent_to_agency",
            "Obras Publicas",
        )
        self.assertEqual(ddb.item["status"]["S"], "sent_to_agency")
        self.assertEqual(ddb.item["routed_to"]["S"], "Obras Publicas")
        self.assertEqual(incident["status"], "pending_send")
        self.assertEqual(len(ddb.updates), 1)
        entry = events.entries[0]
        detail = json.loads(entry["Detail"])
        self.assertEqual(detail["user_ids"], [])
        self.assertEqual(detail["authority"], "Obras Publicas")

        ses = FakeSES()
        with mock.patch.object(mailer, "_ddb", ddb), mock.patch.object(mailer, "_ses", ses):
            sent = mailer.lambda_handler({
                "id": "evt-send", "source": entry["Source"], "detail-type": entry["DetailType"],
                "detail": detail,
            }, None)
        self.assertTrue(sent["sent"])
        self.assertEqual(ses.sent[0]["Destination"]["ToAddresses"], ["obras@example.com"])
        self.assertTrue(ddb.item["dependency_mail_sent_at"]["S"])
        self.assertEqual(ddb.audit[-1]["message_id"]["S"], "ses-message-1")

        shown = portal.to_incident(ddb.item)
        self.assertEqual(shown["status"], "sent_to_agency")
        self.assertNotIn("sent_to_agency", portal.allowed_transitions(shown["status"], True))

    def test_send_to_an_agency_without_mailbox_goes_to_supervisor_and_stays_pending(self):
        _, ddb, events = _supervisor_sets(_open_item(), "sent_to_agency", "Seguridad Ciudadana")
        entry = events.entries[0]
        ses = FakeSES()
        with mock.patch.object(mailer, "_ddb", ddb), mock.patch.object(mailer, "_ses", ses):
            mailer.lambda_handler({
                "id": "evt-sec", "source": entry["Source"], "detail-type": entry["DetailType"],
                "detail": json.loads(entry["Detail"]),
            }, None)
        self.assertEqual(ses.sent[0]["Destination"]["ToAddresses"], ["supervisor@example.com"])
        self.assertNotIn("dependency_mail_sent_at", ddb.item)
        self.assertEqual(portal.to_incident(ddb.item)["status"], "pending_send")


if __name__ == "__main__":
    unittest.main()
