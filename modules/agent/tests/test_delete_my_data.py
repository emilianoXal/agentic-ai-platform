"""Behavior tests for the personal-data deletion Lambda."""

import hashlib
import hmac
import importlib.util
import json
import logging
import os
from pathlib import Path
from unittest import mock

from botocore.exceptions import ClientError

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "USERS_TABLE": "users",
    "PLACES_TABLE": "places",
    "REPORTS_TABLE": "reports",
    "INCIDENTS_TABLE": "incidents",
    "AUDIT_TABLE": "audit",
})

_HANDLER_PATH = Path(__file__).parents[1] / "src" / "delete_my_data" / "handler.py"
_spec = importlib.util.spec_from_file_location("delete_my_data_handler", _HANDLER_PATH)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


class FakeDynamoDB:
    def __init__(self):
        self.users = {
            "5215512345678": {
                "user_id": {"S": "5215512345678"},
                "phone": {"S": "5215512345678"},
                "opt_in": {"BOOL": True},
            },
        }
        self.places = {
            ("5215512345678", "home"): {
                "user_id": {"S": "5215512345678"},
                "place_id": {"S": "home"},
                "alias": {"S": "Casa"},
            },
        }
        self.reports = {
            "report-1": {
                "report_id": {"S": "report-1"},
                "user_id": {"S": "5215512345678"},
                "phone": {"S": "5215512345678"},
                "incident_id": {"S": "incident-1"},
            },
            "report-joined": {
                "report_id": {"S": "report-joined"},
                "user_id": {"S": "5215512345678"},
            },
        }
        self.incidents = {
            "incident-1": {
                "incident_id": {"S": "incident-1"},
                "report_count": {"N": "1"},
                "subscribers": {"SS": ["5215512345678", "5215500000000"]},
            },
            "incident-joined": {
                "incident_id": {"S": "incident-joined"},
                "report_count": {"N": "2"},
                "subscribers": {"SS": ["5215512345678"]},
            },
        }
        self.audit = []

    def query(self, TableName, **kwargs):
        user_id = kwargs["ExpressionAttributeValues"][":u"]["S"]
        if TableName == "places":
            return {
                "Items": [
                    {"user_id": item["user_id"], "place_id": item["place_id"]}
                    for item in self.places.values()
                    if item["user_id"]["S"] == user_id
                ],
            }
        return {
            "Items": [
                {"report_id": item["report_id"]}
                for item in self.reports.values()
                if item.get("user_id", {}).get("S") == user_id
            ],
        }

    def scan(self, TableName, FilterExpression, ExpressionAttributeValues, **kwargs):
        assert TableName == "incidents"
        user_id = ExpressionAttributeValues[":u"]["S"]
        return {
            "Items": [
                {"incident_id": item["incident_id"]}
                for item in self.incidents.values()
                if user_id in item.get("subscribers", {}).get("SS", [])
            ],
        }

    def delete_item(self, TableName, Key):
        if TableName == "users":
            self.users.pop(Key["user_id"]["S"], None)
        else:
            self.places.pop((Key["user_id"]["S"], Key["place_id"]["S"]), None)

    def update_item(self, TableName, Key, **kwargs):
        if TableName == "incidents":
            incident = self.incidents[Key["incident_id"]["S"]]
            removed = kwargs["ExpressionAttributeValues"][":sub"]["SS"]
            remaining = [
                sub for sub in incident.get("subscribers", {}).get("SS", [])
                if sub not in removed
            ]
            if remaining:
                incident["subscribers"] = {"SS": remaining}
            else:
                incident.pop("subscribers", None)
            return {}
        report = self.reports[Key["report_id"]["S"]]
        for field in kwargs["ExpressionAttributeNames"].values():
            report.pop(field, None)

    def put_item(self, TableName, Item):
        self.audit.append(Item)


def test_delete_removes_personal_data_and_preserves_incident_count():
    database = FakeDynamoDB()
    handler._ddb = database

    result = handler.lambda_handler(
        {"user_id": "5215512345678", "confirmed": True}, None,
    )

    assert result == {
        "ok": True,
        "places_deleted": 1,
        "reports_anonymized": 2,
        "memory_events_deleted": 0,
        "memory_records_deleted": 0,
    }
    assert database.users == {}
    assert database.places == {}
    assert database.reports["report-1"] == {
        "report_id": {"S": "report-1"},
        "incident_id": {"S": "incident-1"},
    }
    assert database.incidents["incident-1"]["report_count"] == {"N": "1"}
    assert database.incidents["incident-1"]["subscribers"] == {"SS": ["5215500000000"]}
    assert database.reports["report-joined"] == {"report_id": {"S": "report-joined"}}
    assert "subscribers" not in database.incidents["incident-joined"]
    assert database.incidents["incident-joined"]["report_count"] == {"N": "2"}
    audit_text = str(database.audit)
    assert "5215512345678" not in audit_text
    assert database.audit[0]["kind"] == {"S": "delete_my_data"}


def test_delete_is_idempotent():
    database = FakeDynamoDB()
    handler._ddb = database
    event = {"user_id": "5215512345678", "confirmed": True}

    assert handler.lambda_handler(event, None)["ok"] is True
    assert handler.lambda_handler(event, None) == {
        "ok": True,
        "places_deleted": 0,
        "reports_anonymized": 0,
        "memory_events_deleted": 0,
        "memory_records_deleted": 0,
    }


def test_delete_requires_explicit_confirmation_without_writes():
    handler._ddb = mock.MagicMock()

    result = handler.lambda_handler({"user_id": "5215512345678"}, None)

    assert result["error"] == "confirmation_required"
    handler._ddb.query.assert_not_called()
    handler._ddb.delete_item.assert_not_called()
    handler._ddb.update_item.assert_not_called()
    handler._ddb.put_item.assert_not_called()


CITIZEN = "5215512345678"
OTHER_CITIZEN = "5215500000000"
IDENTITY_KEY = "identity-key-one"
MEMORY_ID = "memory-1234567890"


def _key(citizen):
    return hmac.new(IDENTITY_KEY.encode(), citizen.encode(), hashlib.sha256).hexdigest()


class FakeAgentCore:
    """Paginated AgentCore data plane keyed by (actorId, sessionId)."""

    def __init__(self, fail_records=False, events_per_citizen=3):
        self.fail_records = fail_records
        self.events = {}
        self.records = {}
        for citizen in (CITIZEN, OTHER_CITIZEN):
            key = _key(citizen)
            self.events[(f"citizen-{key}", f"conversation-{key}")] = [
                f"{citizen}-event-{n}" for n in range(events_per_citizen)
            ]
            self.records[f"{citizen}-record"] = [f"/strategies/s1/actors/citizen-{key}"]

    def list_events(self, memoryId, actorId, sessionId, includePayloads, nextToken=None):
        assert memoryId == MEMORY_ID and includePayloads is False
        events = self.events.get((actorId, sessionId), [])
        start = int(nextToken or 0)
        page = {"events": [{"eventId": e} for e in events[start:start + 2]]}
        if start + 2 < len(events):
            page["nextToken"] = str(start + 2)
        return page

    def delete_event(self, memoryId, actorId, sessionId, eventId):
        self.events[(actorId, sessionId)].remove(eventId)

    def list_memory_records(self, memoryId, namespace, nextToken=None):
        assert namespace == "/"
        return {"memoryRecordSummaries": [
            {"memoryRecordId": record_id, "namespaces": namespaces}
            for record_id, namespaces in self.records.items()
        ]}

    def batch_delete_memory_records(self, memoryId, records):
        if self.fail_records:
            return {"successfulRecords": [], "failedRecords": [
                {"memoryRecordId": r["memoryRecordId"], "errorCode": 500}
                for r in records
            ]}
        for record in records:
            del self.records[record["memoryRecordId"]]
        return {"successfulRecords": records, "failedRecords": []}


def _with_memory(agentcore):
    secrets = mock.MagicMock()
    secrets.get_secret_value.return_value = {"SecretString": IDENTITY_KEY}
    return mock.patch.multiple(
        handler,
        _agentcore=agentcore,
        _secrets=secrets,
        AGENTCORE_MEMORY_ID=MEMORY_ID,
        AGENTCORE_IDENTITY_SECRET_ARN="arn:aws:secretsmanager:us-east-1:1:secret:id",
    )


def test_delete_erases_only_this_citizens_agentcore_memory():
    database = FakeDynamoDB()
    handler._ddb = database
    agentcore = FakeAgentCore()

    with _with_memory(agentcore):
        result = handler.lambda_handler({"user_id": CITIZEN, "confirmed": True}, None)

    assert result["ok"] is True
    assert result["memory_events_deleted"] == 3
    assert result["memory_records_deleted"] == 1
    key, other = _key(CITIZEN), _key(OTHER_CITIZEN)
    assert agentcore.events[(f"citizen-{key}", f"conversation-{key}")] == []
    assert len(agentcore.events[(f"citizen-{other}", f"conversation-{other}")]) == 3
    assert list(agentcore.records) == [f"{OTHER_CITIZEN}-record"]
    assert database.audit[0]["memory_erased"] == {"BOOL": True}


def test_delete_reports_incomplete_memory_erasure_without_personal_data(caplog):
    database = FakeDynamoDB()
    handler._ddb = database
    agentcore = FakeAgentCore(fail_records=True)

    with _with_memory(agentcore), caplog.at_level(logging.INFO):
        result = handler.lambda_handler({"user_id": CITIZEN, "confirmed": True}, None)

    assert result["ok"] is False
    assert result["error"] == "memory_erasure_failed"
    assert database.users == {}
    assert database.audit[0]["memory_erased"] == {"BOOL": False}
    logged = [json.loads(r.getMessage()) for r in caplog.records]
    assert [entry["event"] for entry in logged] == ["agentcore_memory_erasure_failed"]
    assert CITIZEN not in caplog.text and _key(CITIZEN) not in caplog.text


def test_delete_reports_memory_api_error_as_incomplete():
    handler._ddb = FakeDynamoDB()
    agentcore = mock.MagicMock()
    agentcore.list_events.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "ListEvents",
    )

    with _with_memory(agentcore):
        result = handler.lambda_handler({"user_id": CITIZEN, "confirmed": True}, None)

    assert result["ok"] is False
    assert result["error"] == "memory_erasure_failed"


class FakeLambdaContext:
    """Remaining time drops 1 s per check, starting from start_ms."""

    def __init__(self, start_ms):
        self.remaining_ms = start_ms

    def get_remaining_time_in_millis(self):
        self.remaining_ms -= 1000
        return self.remaining_ms


def test_delete_stops_memory_erasure_before_timeout_and_retry_finishes(caplog):
    database = FakeDynamoDB()
    handler._ddb = database
    agentcore = FakeAgentCore(events_per_citizen=40)
    key = _key(CITIZEN)
    session = (f"citizen-{key}", f"conversation-{key}")
    event = {"user_id": CITIZEN, "confirmed": True}

    with _with_memory(agentcore), caplog.at_level(logging.INFO):
        first = handler.lambda_handler(event, FakeLambdaContext(start_ms=30000))

    assert first["ok"] is False
    assert first["error"] == "memory_erasure_failed"
    assert 0 < len(agentcore.events[session]) < 40
    assert database.audit[-1]["memory_erased"] == {"BOOL": False}
    logged = [json.loads(r.getMessage()) for r in caplog.records]
    assert logged[-1]["event"] == "agentcore_memory_erasure_failed"
    assert CITIZEN not in caplog.text and key not in caplog.text

    with _with_memory(agentcore):
        retried = handler.lambda_handler(event, FakeLambdaContext(start_ms=900000))

    assert retried["ok"] is True
    assert agentcore.events[session] == []
    assert list(agentcore.records) == [f"{OTHER_CITIZEN}-record"]
    assert database.audit[-1]["memory_erased"] == {"BOOL": True}
