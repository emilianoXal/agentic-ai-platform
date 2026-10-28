"""Closed report categories are stored, routed, and counted.

Run: python3 -m pytest -q modules/agent/tests/test_categoria_catalogo.py
"""

import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import boto3
from moto import mock_aws

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "REPORTS_TABLE": "reports",
    "INCIDENTS_TABLE": "incidents",
    "INCIDENTS_GEOHASH_INDEX": "by-geohash",
    "AUDIT_TABLE": "audit",
    "EVENTS_BUS_NAME": "bus",
    "PENDING_MEDIA_TABLE": "",
})

_strands = mock.MagicMock()
sys.modules.setdefault("strands", _strands).tool = lambda fn: fn
sys.modules.setdefault("strands.models.bedrock", mock.MagicMock())
_exceptions = mock.MagicMock()
_exceptions.ModelThrottledException = type("ModelThrottled", (Exception,), {})
sys.modules.setdefault("strands.types.exceptions", _exceptions)

_MODULES = Path(__file__).resolve().parents[2]
_REPO = _MODULES.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent = _load("categoria_agent", _MODULES / "agent" / "src" / "agent" / "handler.py")
create_report = _load("categoria_create_report", _MODULES / "agent" / "src" / "create_report" / "handler.py")
join_incident = _load("categoria_join_incident", _MODULES / "agent" / "src" / "join_incident" / "handler.py")
route = _load("categoria_route", _MODULES / "agent" / "src" / "route" / "handler.py")
matrix = _load("categoria_matrix", _REPO / "scripts" / "conversation_matrix.py")

SENDER = "5215500000001"
GEOHASH = "9g3qrbc"


class FakeEvents:
    def __init__(self):
        self.entries = []

    def put_events(self, Entries):
        self.entries.extend(Entries)
        return {"FailedEntryCount": 0, "Entries": [{"EventId": "evt-1"}]}


def _tables(ddb):
    ddb.create_table(
        TableName="reports",
        KeySchema=[{"AttributeName": "report_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "report_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="incidents",
        KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "incident_id", "AttributeType": "S"},
            {"AttributeName": "geohash", "AttributeType": "S"},
            {"AttributeName": "updated_at", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "by-geohash",
            "KeySchema": [
                {"AttributeName": "geohash", "KeyType": "HASH"},
                {"AttributeName": "updated_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="audit",
        KeySchema=[
            {"AttributeName": "entity_id", "KeyType": "HASH"},
            {"AttributeName": "ts", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "entity_id", "AttributeType": "S"},
            {"AttributeName": "ts", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self._aws = mock_aws()
        self._aws.start()
        self.ddb = boto3.client("dynamodb", region_name="us-east-1")
        _tables(self.ddb)
        self.events = FakeEvents()
        create_report._ddb = self.ddb
        join_incident._ddb = self.ddb
        route._ddb = self.ddb
        route._events = self.events
        self.calls = []

        def invoke(FunctionName, InvocationType, Payload):
            self.calls.append(FunctionName)
            tool = {
                "create-report": create_report,
                "join-incident": join_incident,
                "route": route,
            }[FunctionName]
            body = tool.lambda_handler(json.loads(Payload), None)
            return {"Payload": io.BytesIO(json.dumps(body).encode())}

        agent._lambda = mock.Mock()
        agent._lambda.invoke.side_effect = invoke
        agent.TOOL_CREATE_REPORT_FN = "create-report"
        agent.TOOL_JOIN_INCIDENT_FN = "join-incident"
        agent.TOOL_ROUTE_FN = "route"
        agent._turn.clear()
        agent._turn["user_id"] = SENDER

    def tearDown(self):
        self._aws.stop()

    def _report(self, category):
        return {
            "user_id": SENDER,
            "category": category,
            "geohash": GEOHASH,
            "description": "Parked patrol car blocking the lane at the corner",
        }

    def test_unknown_category_is_rejected_and_stores_nothing(self):
        for category in ("obstruction", "drenaje", "BACHE"):
            result = create_report.lambda_handler(self._report(category), None)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "unknown_category")
            self.assertEqual(set(result["allowed"]), set(matrix.CATEGORY_CATALOG))
        self.assertEqual(self.ddb.scan(TableName="reports")["Count"], 0)
        self.assertEqual(self.ddb.scan(TableName="incidents")["Count"], 0)
        joined = join_incident.lambda_handler({
            "incident_id": "inc-1",
            "user_id": SENDER,
            "category": "obstruction",
            "geohash": GEOHASH,
        }, None)
        self.assertEqual(joined["error"], "unknown_category")
        self.assertEqual(self.ddb.scan(TableName="reports")["Count"], 0)

    def test_catalog_report_is_stored_and_routed_to_its_dependency(self):
        created = create_report.lambda_handler(self._report("Bacheo"), None)
        self.assertTrue(created["ok"])
        self.assertEqual(created["category"], "bacheo")
        routed = route.lambda_handler({
            "category": created["category"],
            "incident_id": created["incident_id"],
        }, None)
        self.assertTrue(routed["ok"])
        self.assertEqual(routed["authority"], "Obras Publicas")
        incident = self.ddb.get_item(
            TableName="incidents",
            Key={"incident_id": {"S": created["incident_id"]}},
            ConsistentRead=True,
        )["Item"]
        self.assertEqual(incident["category"]["S"], "bacheo")
        self.assertEqual(incident["routed_to"]["S"], "Obras Publicas")
        self.assertEqual(self.events.entries[0]["DetailType"], "StatusChanged")

    def test_every_catalog_category_resolves_and_unknown_does_not(self):
        authorities = {}
        for category in matrix.CATEGORY_CATALOG:
            result = route.lambda_handler({"category": category}, None)
            self.assertTrue(result["ok"], category)
            authorities[category] = result["authority"]
        self.assertEqual(authorities["otro"], "Supervisor municipal")
        self.assertEqual(authorities["agua"], "Organismo de Agua")
        refused = route.lambda_handler({"category": "obstruction"}, None)
        self.assertEqual(refused["error"], "no_route")

    def test_wrapper_routes_after_create_and_not_after_rejection(self):
        rejected = agent.create_report(
            category="obstruction", geohash=GEOHASH, description="parked car blocking the lane",
        )
        self.assertFalse(rejected["ok"])
        self.assertEqual(self.calls, ["create-report"])
        self.assertNotIn("route", rejected)

        self.calls.clear()
        created = agent.create_report(
            category="bacheo", geohash=GEOHASH, description="deep pothole",
        )
        self.assertTrue(created["ok"])
        self.assertEqual(self.calls, ["create-report", "route"])
        self.assertEqual(created["route"]["authority"], "Obras Publicas")
        incident = self.ddb.get_item(
            TableName="incidents",
            Key={"incident_id": {"S": created["incident_id"]}},
            ConsistentRead=True,
        )["Item"]
        self.assertEqual(incident["routed_to"]["S"], "Obras Publicas")

    def test_wrapper_routes_a_joined_catalog_report(self):
        self.ddb.put_item(TableName="incidents", Item={
            "incident_id": {"S": "inc-1"},
            "status": {"S": "OPEN"},
            "category": {"S": "bacheo"},
            "geohash": {"S": GEOHASH},
            "updated_at": {"S": "2026-10-28T00:00:00+00:00"},
            "report_count": {"N": "1"},
        })
        joined = agent.join_incident(incident_id="inc-1", category="Bacheo", geohash=GEOHASH)
        self.assertTrue(joined["ok"])
        self.assertEqual(joined["category"], "bacheo")
        self.assertEqual(joined["route"]["authority"], "Obras Publicas")
        incident = self.ddb.get_item(
            TableName="incidents",
            Key={"incident_id": {"S": "inc-1"}},
            ConsistentRead=True,
        )["Item"]
        self.assertEqual(incident["routed_to"]["S"], "Obras Publicas")


class MatrixCatalogTests(unittest.TestCase):
    def test_probe_verdict_rejects_unknown_and_counts_routed(self):
        obstruction = next(case for case in matrix.CASES if case.get("probe") == "obstruccion")
        pothole = next(case for case in matrix.CASES if case.get("probe") == "bache")
        bad = {
            "turns": [{
                "response": {"ok": True, "reply": "I saved that report."},
                "tool_evidence": [{"tool": "create_report"}, {"tool": "route"}],
            }],
            "ddb_after": {
                "user_reports": [{"category": "obstruction"}],
                "linked_incident": {},
            },
        }
        refused = matrix.verdicts(obstruction, bad, None)
        self.assertFalse(refused["accion_correcta"]["pass"])
        self.assertFalse(refused["veracidad"]["pass"])
        self.assertIn("obstruction", refused["accion_correcta"]["evidence"])

        good = {
            "turns": [{
                "response": {"ok": True, "reply": "Obras Publicas has the pothole."},
                "tool_evidence": [{"tool": "create_report"}, {"tool": "route"}],
            }],
            "ddb_after": {
                "user_reports": [{"category": "bacheo"}],
                "linked_incident": {"routed_to": "Obras Publicas"},
            },
        }
        accepted = matrix.verdicts(pothole, good, None)
        self.assertTrue(accepted["accion_correcta"]["pass"])
        self.assertTrue(accepted["veracidad"]["pass"])
        self.assertTrue(accepted["idioma_es_mx"]["pass"])

        counts = matrix.category_counts(
            [obstruction, pothole],
            [
                {"case_id": obstruction["id"], "ddb_after": bad["ddb_after"]},
                {"case_id": pothole["id"], "ddb_after": good["ddb_after"]},
            ],
        )
        self.assertEqual(counts["obstruction"], {"chosen": 1, "routed": 0})
        self.assertEqual(counts["bacheo"], {"chosen": 1, "routed": 1})
        rendered = matrix.render_markdown({
            "finished_at": "t",
            "function_name": "agent",
            "bedrock_model_id": "sonnet",
            "matrix_source": "built-in",
            "case_summary": [],
            "runs": [],
            "category_counts": counts,
        })
        self.assertIn("| bacheo | 1 | 1 |", rendered)
        self.assertIn("| obstruction | 1 | 0 |", rendered)

    def test_category_probes_ride_the_base_suite(self):
        base = matrix.select_cases("base")
        probes = [case for case in base if case.get("category_probe")]
        self.assertEqual([case["probe"] for case in probes], [
            "bache", "alumbrado", "basura", "agua", "obstruccion", "ambiguo",
        ])
        parked = next(case for case in probes if case["probe"] == "obstruccion")
        self.assertIn("Parked patrol car blocking the lane at the corner", parked["turns"][0])
        self.assertEqual(parked["required_tools"], ["create_report", "route"])
        follow_up = matrix.select_cases("follow-up")
        self.assertTrue(all(case.get("follow_up") for case in follow_up))
        self.assertFalse(any(case.get("category_probe") for case in follow_up))


if __name__ == "__main__":
    unittest.main()
