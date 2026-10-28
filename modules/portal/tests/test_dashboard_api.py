"""Unit tests for the dashboard API Lambda (no AWS calls: DynamoDB and
EventBridge are replaced with in-memory fakes).

Run: python3 -m unittest discover -s modules/portal/tests
"""

import json
import os
import sys
import unittest
from datetime import datetime, timezone

os.environ.update({
    "INCIDENTS_TABLE_NAME": "incidents",
    "REPORTS_TABLE_NAME": "reports",
    "AUDIT_TABLE_NAME": "audit",
    "USERS_TABLE_NAME": "users",
    "EVENT_BUS_NAME": "bus",
    "AWS_DEFAULT_REGION": "us-east-1",
})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "dashboard_api"))

import demo_data  # noqa: E402
import handler  # noqa: E402


class FakeDynamo:
    """Just enough of the DynamoDB client for the handler's calls."""

    KEYS = {"incidents": ["incident_id"], "reports": ["report_id"], "audit": ["entity_id", "ts"], "users": ["user_id"]}

    def __init__(self):
        self.tables = {name: {} for name in self.KEYS}

    def _key(self, table, item):
        return tuple(item[k]["S"] for k in self.KEYS[table])

    def put_item(self, TableName, Item):
        self.tables[TableName][self._key(TableName, Item)] = Item

    def get_item(self, TableName, Key):
        item = self.tables[TableName].get(self._key(TableName, Key))
        return {"Item": item} if item else {}

    def update_item(self, TableName, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None, ConditionExpression=None):
        item = self.tables[TableName].setdefault(self._key(TableName, Key), dict(Key))
        names = ExpressionAttributeNames or {}
        set_part = UpdateExpression.split(" REMOVE ")[0].replace("SET ", "")
        for assignment in set_part.split(", "):
            attr, value = [p.strip() for p in assignment.split("=")]
            item[names.get(attr, attr)] = ExpressionAttributeValues[value]
        if " REMOVE " in UpdateExpression:
            item.pop(UpdateExpression.split(" REMOVE ")[1].strip(), None)

    def batch_get_item(self, RequestItems):
        out = {}
        for table, spec in RequestItems.items():
            out[table] = [self.tables[table][self._key(table, k)] for k in spec["Keys"] if self._key(table, k) in self.tables[table]]
        return {"Responses": out}

    def batch_write_item(self, RequestItems):
        for table, requests in RequestItems.items():
            for request in requests:
                if "PutRequest" in request:
                    self.put_item(table, request["PutRequest"]["Item"])
                else:
                    self.tables[table].pop(self._key(table, request["DeleteRequest"]["Key"]), None)
        return {}

    def query(self, TableName, KeyConditionExpression, ExpressionAttributeValues, ScanIndexForward=True, Limit=None, ProjectionExpression=None, ExclusiveStartKey=None):
        entity = ExpressionAttributeValues[":e"]["S"]
        items = [i for k, i in self.tables[TableName].items() if k[0] == entity]
        items.sort(key=lambda i: i["ts"]["S"], reverse=not ScanIndexForward)
        return {"Items": items[:Limit] if Limit else items}

    def scan(self, TableName, Limit=None, ExclusiveStartKey=None, FilterExpression=None, ExpressionAttributeValues=None, ProjectionExpression=None):
        items = list(self.tables[TableName].values())
        if FilterExpression:
            items = [i for i in items if i.get("synthetic", {}).get("BOOL")]
        return {"Items": items[:Limit] if Limit else items}


class FakeEvents:
    def __init__(self):
        self.entries = []

    def put_events(self, Entries):
        self.entries.extend(Entries)


def event(field, parent="Mutation", groups=("official",), agency=None, **arguments):
    claims = {"cognito:groups": list(groups), "email": "staff@example.com"}
    if agency:
        claims["custom:agency_id"] = agency
    return {"info": {"parentTypeName": parent, "fieldName": field}, "arguments": arguments, "identity": {"claims": claims}}


class DashboardApiTest(unittest.TestCase):
    def setUp(self):
        self.ddb = FakeDynamo()
        self.events = FakeEvents()
        handler._ddb = self.ddb
        handler._events = self.events
        incidents, reports, audit, users = demo_data.build(20.5931, -100.3921, lambda lat, lng: {"address": "Calle Madero 10", "neighborhood": "Centro"})
        for table, items in (("incidents", incidents), ("reports", reports), ("audit", audit), ("users", users)):
            for item in items:
                self.ddb.put_item(table, item)
        self.leak = next(i for i in incidents if i["category"]["S"] == "agua")["incident_id"]["S"]

    def test_demo_set_has_30_reports_in_4_incidents(self):
        self.assertEqual(len(self.ddb.tables["incidents"]), 4)
        self.assertEqual(len(self.ddb.tables["reports"]), 30)
        self.assertTrue(all(i["synthetic"]["BOOL"] for i in self.ddb.tables["incidents"].values()))

    def test_list_returns_paginated_read_model(self):
        page = handler.lambda_handler(event("listIncidents", parent="Query", limit=50), None)
        self.assertEqual(page["count"], 4)
        self.assertFalse(page["hasMore"])
        leak = next(i for i in page["items"] if i["id"] == self.leak)
        self.assertEqual(leak["status"], "sent_to_agency")
        self.assertEqual(leak["agencyId"], "organismo-de-agua")
        self.assertEqual(leak["title"], "Water leak at Calle Madero 10")

    def test_list_rejects_oversized_pages(self):
        with self.assertRaises(Exception) as ctx:
            handler.lambda_handler(event("listIncidents", parent="Query", limit=500), None)
        self.assertIn("invalid_input", str(ctx.exception))

    def test_agency_operator_sees_only_its_agency(self):
        page = handler.lambda_handler(event("listIncidents", parent="Query", groups=("agency",), agency="organismo-de-agua"), None)
        self.assertEqual([i["id"] for i in page["items"]], [self.leak])

    def test_detail_masks_neighbors_and_builds_timeline(self):
        detail = handler.lambda_handler(event("getIncident", parent="Query", id=self.leak), None)
        self.assertEqual(len(detail["neighbors"]), 12)
        self.assertTrue(all(n.startswith("••") and len(n) == 4 for n in detail["neighbors"]))
        kinds = {e["kind"] for e in detail["timeline"]}
        self.assertTrue({"status", "joined", "routed"} <= kinds)

    def test_status_change_notifies_every_neighbor(self):
        result = handler.lambda_handler(event("updateIncidentStatus", groups=("agency",), agency="organismo-de-agua", id=self.leak, status="in_progress"), None)
        self.assertEqual(result["notified"], 12)
        self.assertEqual(result["incident"]["status"], "in_progress")
        detail = json.loads(self.events.entries[-1]["Detail"])
        self.assertEqual(self.events.entries[-1]["DetailType"], "StatusChanged")
        self.assertEqual(len(detail["user_ids"]), 12)
        reports = [r for r in self.ddb.tables["reports"].values() if r["incident_id"]["S"] == self.leak]
        self.assertTrue(all(r["status"]["S"] == "En atencion" for r in reports))

    def test_operator_cannot_touch_another_agency(self):
        pothole = next(i for i in self.ddb.tables["incidents"].values() if i["category"]["S"] == "bacheo")["incident_id"]["S"]
        with self.assertRaises(Exception) as ctx:
            handler.lambda_handler(event("updateIncidentStatus", groups=("agency",), agency="organismo-de-agua", id=pothole, status="in_progress"), None)
        self.assertIn("forbidden", str(ctx.exception))

    def test_invalid_transition_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            handler.lambda_handler(event("updateIncidentStatus", id=self.leak, status="resolved"), None)
        self.assertIn("invalid_transition", str(ctx.exception))

    def test_not_applicable_requires_a_reason(self):
        with self.assertRaises(Exception) as ctx:
            handler.lambda_handler(event("updateIncidentStatus", id=self.leak, status="not_applicable"), None)
        self.assertIn("reason", str(ctx.exception))

    def test_resolve_schedules_follow_up(self):
        handler.lambda_handler(event("updateIncidentStatus", id=self.leak, status="in_progress"), None)
        result = handler.lambda_handler(event("updateIncidentStatus", id=self.leak, status="resolved"), None)
        self.assertTrue(result["incident"]["followUpPending"])

    def test_only_supervisors_escalate(self):
        with self.assertRaises(Exception):
            handler.lambda_handler(event("escalateIncident", groups=("agency",), agency="organismo-de-agua", id=self.leak), None)
        incident = handler.lambda_handler(event("escalateIncident", id=self.leak), None)
        self.assertTrue(incident["escalated"])

    def test_only_admin_resets_demo_and_only_synthetic_rows_go(self):
        real = {"incident_id": {"S": "real-1"}, "category": {"S": "agua"}, "geohash": {"S": "9ewmq3h"}, "status": {"S": "OPEN"}, "created_at": {"S": "2026-10-27T10:00:00+00:00"}}
        self.ddb.put_item("incidents", real)
        with self.assertRaises(Exception):
            handler.lambda_handler(event("resetDemoData"), None)
        removed = handler.lambda_handler(event("resetDemoData", groups=("admin",)), None)
        self.assertEqual(removed, 4)
        self.assertEqual(list(self.ddb.tables["incidents"]), [("real-1",)])


class ReadModelTest(unittest.TestCase):
    def test_legacy_statuses_are_normalized(self):
        self.assertEqual(handler.normalize_status("OPEN", routed=False), ("received", False))
        self.assertEqual(handler.normalize_status("OPEN", routed=True), ("sent_to_agency", False))
        self.assertEqual(handler.normalize_status("ESCALATED", routed=True), ("sent_to_agency", True))
        self.assertEqual(handler.normalize_status("En atención", routed=True), ("in_progress", False))
        self.assertEqual(handler.normalize_status("resolved", routed=True), ("resolved", False))

    def test_geohash_round_trip(self):
        geohash = demo_data.encode_geohash(20.5931, -100.3921)
        lat, lng = handler.decode_geohash(geohash)
        self.assertAlmostEqual(lat, 20.5931, places=2)
        self.assertAlmostEqual(lng, -100.3921, places=2)

    def test_incident_without_coordinates_uses_geohash_center(self):
        item = {"incident_id": {"S": "abc123"}, "category": {"S": "bacheo"}, "geohash": {"S": demo_data.encode_geohash(20.6, -100.4)}, "status": {"S": "OPEN"}, "created_at": {"S": datetime(2026, 10, 27, tzinfo=timezone.utc).isoformat()}}
        incident = handler.to_incident(item)
        self.assertAlmostEqual(incident["location"]["lat"], 20.6, places=2)
        self.assertEqual(incident["folio"], "FY-2026-ABC123")
        self.assertEqual(incident["status"], "received")

    def test_agency_slug(self):
        self.assertEqual(handler.slugify("Organismo de Agua"), "organismo-de-agua")
        self.assertEqual(handler.slugify("Servicios Públicos"), "servicios-publicos")


if __name__ == "__main__":
    unittest.main()
