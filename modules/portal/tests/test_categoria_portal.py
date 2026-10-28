"""The portal says sent to agency only with a dependency mail and a dependency.

Run: python3 -m pytest -q modules/portal/tests/test_categoria_portal.py
"""

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
