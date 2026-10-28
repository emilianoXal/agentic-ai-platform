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

from botocore.exceptions import ClientError


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
        "DEPENDENCY_MAIL_CATEGORIES": "agua,alumbrado,bacheo,basura,drenaje,arbol,plagas",
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
        "REPORTS_TABLE": "reports",
        "AUDIT_TABLE": "audit",
        "EVENT_BUS_NAME": "bus",
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
    def __init__(self, item, reports=None):
        self.item = item
        self.reports = reports or {}
        self.updates = []
        self.audit = []
        self.claims = set()

    def get_item(self, TableName, Key, ConsistentRead=False):
        return {"Item": dict(self.item)}

    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeValues,
                    ExpressionAttributeNames=None, ConditionExpression=None, ReturnValues=None):
        target = self.reports[Key["report_id"]["S"]] if TableName == "reports" else self.item
        if TableName != "reports":
            self.updates.append(UpdateExpression)
        names = ExpressionAttributeNames or {}
        for assignment in UpdateExpression.split(" REMOVE ")[0].replace("SET ", "").split(", "):
            attr, value = [part.strip() for part in assignment.split("=")]
            target[names.get(attr, attr)] = ExpressionAttributeValues[value]
        return {"Attributes": dict(target)}

    def put_item(self, TableName, Item, ConditionExpression=None):
        if not ConditionExpression:
            self.audit.append(Item)
            return
        key = Item["entity_id"]["S"]
        if key in self.claims:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.claims.add(key)

    def delete_item(self, TableName, Key):
        self.claims.discard(Key["entity_id"]["S"])

    def batch_get_item(self, RequestItems):
        return {"Responses": {}}

    def query(self, **_):
        return {"Items": []}


class FakeEvents:
    def __init__(self):
        self.entries = []

    def put_events(self, Entries):
        self.entries.extend(Entries)


def _supervisor_sets(item, status, dependency=None, reports=None):
    ddb, events = FakeDynamo(item, reports), FakeEvents()
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
        self.assertEqual(line["text"], "Escalated to the supervisor: no agency mailbox")
        self.assertIsNone(line["status"])
        self.assertTrue(shown["escalated"])
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

    def _mail(self, ddb, entry, event_id):
        ses, events = FakeSES(), FakeEvents()
        with mock.patch.object(mailer, "_ddb", ddb), mock.patch.object(mailer, "_ses", ses), \
                mock.patch.object(mailer, "_events", events):
            result = mailer.lambda_handler({
                "id": event_id, "source": entry["Source"], "detail-type": entry["DetailType"],
                "detail": json.loads(entry["Detail"]),
            }, None)
        return result, ses, events

    def test_send_with_a_chosen_dependency_mails_it_then_tells_neighbors_once(self):
        reports = {
            "rep-1": {"report_id": {"S": "rep-1"}, "user_id": {"S": "5215500000001"}, "status": {"S": "Recibido"}},
            "rep-2": {"report_id": {"S": "rep-2"}, "user_id": {"S": "5215500000002"}, "status": {"S": "Recibido"}},
        }
        incident, ddb, events = _supervisor_sets(
            _open_item(category={"S": "otro"}, report_ids={"L": [{"S": "rep-1"}, {"S": "rep-2"}]}),
            "sent_to_agency",
            "Obras Publicas",
            reports,
        )
        self.assertEqual(ddb.item["status"]["S"], "sent_to_agency")
        self.assertEqual(ddb.item["routed_to"]["S"], "Obras Publicas")
        self.assertEqual(incident["status"], "pending_send")
        self.assertEqual({r["status"]["S"] for r in reports.values()}, {"Recibido"})
        portal_event = events.entries[0]
        self.assertEqual(json.loads(portal_event["Detail"])["user_ids"], [])

        sent, ses, notices = self._mail(ddb, portal_event, "evt-send")
        self.assertTrue(sent["sent"])
        self.assertEqual(ses.sent[0]["Destination"]["ToAddresses"], ["obras@example.com"])
        self.assertTrue(ddb.item["dependency_mail_sent_at"]["S"])
        self.assertTrue(any(a.get("message_id", {}).get("S") == "ses-message-1" for a in ddb.audit))
        self.assertEqual({r["status"]["S"] for r in reports.values()}, {"Enviado a dependencia"})
        self.assertEqual(len(notices.entries), 1)
        notice = notices.entries[0]
        self.assertEqual(notice["DetailType"], "StatusChanged")
        self.assertEqual(sorted(json.loads(notice["Detail"])["user_ids"]), ["5215500000001", "5215500000002"])

        echoed, ses_again, notices_again = self._mail(ddb, notice, "evt-notice")
        self.assertTrue(echoed["ignored"])
        redelivered, ses_dup, _ = self._mail(ddb, portal_event, "evt-send-2")
        self.assertTrue(redelivered["duplicate"])
        self.assertEqual(ses_again.sent + ses_dup.sent, [])
        self.assertEqual(notices_again.entries, [])

        shown = portal.to_incident(ddb.item)
        self.assertEqual(shown["status"], "sent_to_agency")
        self.assertNotIn("sent_to_agency", portal.allowed_transitions(shown["status"], True))

    def test_no_mailbox_agency_is_a_supervisor_escalation_never_sent(self):
        agencies = {a["name"]: a["mailbox"] for a in portal._agencies()}
        self.assertFalse(agencies["Seguridad Ciudadana"])
        self.assertTrue(agencies["Obras Publicas"])
        self.assertNotIn("Supervisor municipal", agencies)
        for dependency in ("Seguridad Ciudadana", "Supervisor municipal"):
            with self.assertRaises(portal.DashboardError):
                _supervisor_sets(_open_item(category={"S": "seguridad"}), "sent_to_agency", dependency)

        mailed = {"S": "2026-10-28T00:01:00+00:00"}
        for status in ("OPEN", "sent_to_agency"):
            for extra in ({}, {"dependency_mail_sent_at": mailed}):
                shown = portal.to_incident(_open_item(
                    status={"S": status}, category={"S": "seguridad"},
                    routed_to={"S": "Seguridad Ciudadana"}, **extra,
                ))
                self.assertEqual(shown["status"], "received", (status, extra))
                self.assertTrue(shown["escalated"])

    def test_dashboard_send_that_falls_back_can_be_retried(self):
        _, ddb, events = _supervisor_sets(_open_item(), "sent_to_agency", "Obras Publicas")
        entry = dict(events.entries[0])
        detail = json.loads(entry["Detail"])
        detail["dependency_categories"] = ["seguridad"]
        entry["Detail"] = json.dumps(detail)
        first, ses, _ = self._mail(ddb, entry, "evt-a")
        self.assertEqual(ses.sent[0]["Destination"]["ToAddresses"], ["supervisor@example.com"])
        self.assertNotIn("dependency_mail_sent_at", ddb.item)
        retry, ses_retry, _ = self._mail(ddb, entry, "evt-b")
        self.assertTrue(retry["sent"])
        self.assertEqual(len(ses_retry.sent), 1)


if __name__ == "__main__":
    unittest.main()
