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


class FakeDynamo:
    def __init__(self, item):
        self.item = item
        self.updates = []
        self.audit = []

    def get_item(self, TableName, Key):
        return {"Item": dict(self.item)}

    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeValues,
                    ExpressionAttributeNames=None, ConditionExpression=None):
        self.updates.append(UpdateExpression)
        names = ExpressionAttributeNames or {}
        for assignment in UpdateExpression.split(" REMOVE ")[0].replace("SET ", "").split(", "):
            attr, value = [part.strip() for part in assignment.split("=")]
            self.item[names.get(attr, attr)] = ExpressionAttributeValues[value]

    def put_item(self, TableName, Item):
        self.audit.append(Item)

    def query(self, **_):
        return {"Items": []}


class FakeEvents:
    def __init__(self):
        self.entries = []

    def put_events(self, Entries):
        self.entries.extend(Entries)


def _supervisor_sets(item, status):
    ddb, events = FakeDynamo(item), FakeEvents()
    with mock.patch.object(portal, "_ddb", ddb), mock.patch.object(portal, "_events", events):
        result = portal.update_status(
            {"arguments": {"id": "inc-1", "status": status}},
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


    def test_stored_sent_to_agency_needs_mail_and_dependency_and_read_does_not_write(self):
        mailed = {"S": "2026-10-28T00:01:00+00:00"}
        routed = {"S": "Obras Publicas"}
        cases = (
            ({"dependency_mail_sent_at": mailed, "routed_to": routed}, "sent_to_agency"),
            ({"routed_to": routed}, "received"),
            ({"dependency_mail_sent_at": mailed}, "received"),
            ({}, "received"),
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

    def test_supervisor_send_assigns_the_default_agency(self):
        for category, agency in (("bacheo", "Obras Publicas"), ("drenaje", "Organismo de Agua"),
                                 ("arbol", "Servicios Publicos"), ("plagas", "Servicios Publicos")):
            incident, ddb, events = _supervisor_sets(_open_item(category={"S": category}), "sent_to_agency")
            self.assertEqual(ddb.item["status"]["S"], "sent_to_agency")
            self.assertEqual(ddb.item["routed_to"]["S"], agency)
            self.assertEqual(incident["status"], "received")
            self.assertEqual(incident["agencyName"], agency)
            detail = json.loads(events.entries[0]["Detail"])
            self.assertEqual(detail["authority"], agency)

            ddb.item["dependency_mail_sent_at"] = {"S": "2026-10-28T00:05:00+00:00"}
            self.assertEqual(portal.to_incident(ddb.item)["status"], "sent_to_agency")

    def test_supervisor_send_without_agency_reads_received(self):
        incident, ddb, _ = _supervisor_sets(_open_item(category={"S": "otro"}), "sent_to_agency")
        self.assertEqual(ddb.item["status"]["S"], "sent_to_agency")
        self.assertNotIn("routed_to", ddb.item)
        self.assertEqual(incident["status"], "received")
        self.assertIsNone(incident["agencyName"])

    def test_existing_dependency_is_kept_on_supervisor_send(self):
        _, ddb, _ = _supervisor_sets(
            _open_item(routed_to={"S": "Limpia Publica"}), "sent_to_agency"
        )
        self.assertEqual(ddb.item["routed_to"]["S"], "Limpia Publica")
        self.assertNotIn("routed_to", ddb.updates[0])


if __name__ == "__main__":
    unittest.main()
