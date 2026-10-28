"""Executable Scheduler, DynamoDB, outbound and tool contracts without AWS."""

import importlib.util
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[3]
SENDER = "5215599900001"
DUE = "2026-10-28T16:02:00+00:00"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    with patch("boto3.client"):
        spec.loader.exec_module(module)
    return module


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for key, value in {"INCIDENTS_TABLE": "incidents", "REPORTS_TABLE": "reports",
                       "USERS_TABLE": "users", "OUTBOUND_FUNCTION_NAME": "outbound",
                       "OUTBOUND_ORIGINATION_PHONE_NUMBER_ID": "phone-number-id-test"}.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        for table, key in (("incidents", "incident_id"), ("reports", "report_id"), ("users", "user_id")):
            spec = dict(TableName=table, KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                        AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
            if table == "reports":
                spec["AttributeDefinitions"].append({"AttributeName": "user_id", "AttributeType": "S"})
                spec["GlobalSecondaryIndexes"] = [{"IndexName": "by-user", "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}], "Projection": {"ProjectionType": "ALL"}}]
            ddb.create_table(**spec)
        ddb.put_item(TableName="incidents", Item={
            "incident_id": {"S": "i1"}, "status": {"S": "resolved"},
            "category": {"S": "agua"}, "follow_up_due_at": {"S": DUE},
            "follow_up_deliveries": {"M": {}}, "report_ids": {"L": [{"S": "r1"}, {"S": "r2"}]},
        })
        for rid in ("r1", "r2"):
            ddb.put_item(TableName="reports", Item={"report_id": {"S": rid}, "incident_id": {"S": "i1"}, "user_id": {"S": SENDER}, "status": {"S": "Resuelto"}})
        ddb.put_item(TableName="users", Item={"user_id": {"S": SENDER}, "consent": {"BOOL": True}})
        handler = load("follow_up_tests", "modules/follow_up/src/handler.py")
        handler._ddb = ddb
        handler._lambda = Mock()
        handler._lambda.invoke.side_effect = lambda **kw: {"Payload": io.BytesIO(b'{"ok":true}')}
        yield handler


def send(app, **extra):
    return app.lambda_handler({"action": "send", "incident_id": "i1", "due_at": DUE, **extra}, None)


def test_one_send_for_repeated_schedule_and_duplicate_reports(app):
    assert send(app) == {"ok": True, "sent": 1}
    assert send(app) == {"ok": True, "sent": 0}
    app._lambda.invoke.assert_called_once()
    call = app._lambda.invoke.call_args.kwargs
    assert call["FunctionName"] == "outbound"
    assert call["InvocationType"] == "RequestResponse"
    payload = json.loads(call["Payload"])
    assert payload["to"] == SENDER
    assert "¿Ya quedó?" in payload["text"]
    assert payload["origination_phone_number_id"] == "phone-number-id-test"


@pytest.mark.parametrize("change", [{"status": {"S": "OPEN"}}, {"follow_up_due_at": {"S": "another-cycle"}}])
def test_obsolete_schedules_never_send(app, change):
    item = app._incident("i1")
    item.update(change)
    app._ddb.put_item(TableName="incidents", Item=item)
    assert send(app)["skipped"] == "stale"
    app._lambda.invoke.assert_not_called()


def test_missing_or_paused_citizen_never_gets_a_message(app):
    app._ddb.delete_item(TableName="users", Key={"user_id": {"S": SENDER}})
    assert send(app)["sent"] == 0
    app._ddb.put_item(TableName="users", Item={"user_id": {"S": SENDER}, "paused": {"BOOL": True}})
    assert send(app)["sent"] == 0
    app._ddb.put_item(TableName="users", Item={"user_id": {"S": SENDER}, "consent": {"BOOL": False}})
    assert send(app)["sent"] == 0
    app._lambda.invoke.assert_not_called()


def test_uncertain_send_is_not_repeated(app):
    app._lambda.invoke.side_effect = TimeoutError("uncertain channel outcome")
    with pytest.raises(TimeoutError):
        send(app)
    assert send(app)["sent"] == 0
    assert app._lambda.invoke.call_count == 1
    assert app.lambda_handler({"action": "pending", "user_id": SENDER}, None)["pending"] == []


@pytest.mark.parametrize("decision,expected", [("confirm", "resolved"), ("reopen", "OPEN")])
def test_citizen_decision_changes_actual_incident_once(app, decision, expected):
    send(app)
    pending = app.lambda_handler({"action": "pending", "user_id": SENDER}, None)
    assert pending["pending"] == [{"incident_id": "i1", "category": "agua", "due_at": DUE}]
    event = {"action": "respond", "user_id": SENDER, "incident_id": "i1", "due_at": DUE, "decision": decision}
    assert app.lambda_handler(event, None)["status"] == expected
    assert app._incident("i1")["status"]["S"] == expected
    assert app.lambda_handler(event, None)["ok"] is False
    assert app.lambda_handler({"action": "pending", "user_id": SENDER}, None)["pending"] == []
    if decision == "reopen":
        assert "follow_up_due_at" not in app._incident("i1")
        status = load("status_follow_up_tests", "modules/agent/src/get_status/handler.py")
        status._ddb = app._ddb
        assert status.lambda_handler({"user_id": SENDER}, None)["reports"][0]["status"] == "OPEN"


def test_foreign_citizen_and_old_generation_cannot_reopen(app):
    send(app)
    event = {"action": "respond", "user_id": "other", "incident_id": "i1", "due_at": DUE, "decision": "reopen"}
    assert app.lambda_handler(event, None)["error"] == "no_pending_follow_up"
    event.update(user_id=SENDER, due_at="old-cycle")
    assert app.lambda_handler(event, None)["error"] == "stale_follow_up"
    assert app._incident("i1")["status"]["S"] == "resolved"


@pytest.fixture
def portal(monkeypatch):
    for key in ("INCIDENTS_TABLE_NAME", "REPORTS_TABLE_NAME", "AUDIT_TABLE_NAME", "USERS_TABLE_NAME", "EVENT_BUS_NAME"):
        monkeypatch.setenv(key, key)
    monkeypatch.syspath_prepend(str(ROOT / "modules/portal/src/dashboard_api"))
    handler = load("portal_follow_up_tests", "modules/portal/src/dashboard_api/handler.py")
    handler.FOLLOW_UP_DELAY_MINUTES = 2
    handler.FOLLOW_UP_FUNCTION_ARN = "arn:aws:lambda:us-east-1:123456789012:function:follow-up"
    handler.FOLLOW_UP_ROLE_ARN = "arn:aws:iam::123456789012:role/cdshack-scheduler"
    handler._now = lambda: datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)
    handler._scheduler = Mock()
    item = {"incident_id": {"S": "i1"}, "status": {"S": "in_progress"}}
    handler._get_item = Mock(return_value=item)
    handler._detail = lambda item: handler.to_incident(item)
    handler._recipients = lambda item: [SENDER]
    return handler


def test_resolve_creates_one_time_utc_schedule_and_generation(portal):
    portal.update_status({"arguments": {"id": "i1", "status": "resolved"}}, {"groups": {"official"}, "name": "Staff"})
    schedule = portal._scheduler.create_schedule.call_args.kwargs
    assert schedule["Name"].startswith("cdshack-")
    assert len(schedule["Name"]) <= 64
    assert schedule["GroupName"] == "default"
    assert schedule["ScheduleExpression"] == "at(2026-10-28T16:02:00)"
    assert schedule["ScheduleExpressionTimezone"] == "UTC"
    assert schedule["ActionAfterCompletion"] == "DELETE"
    assert schedule["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert schedule["Target"]["Arn"] == portal.FOLLOW_UP_FUNCTION_ARN
    assert schedule["Target"]["RoleArn"] == portal.FOLLOW_UP_ROLE_ARN
    assert json.loads(schedule["Target"]["Input"]) == {"action": "send", "incident_id": "i1", "due_at": DUE}
    values = portal._ddb.update_item.call_args_list[0].kwargs["ExpressionAttributeValues"]
    assert values[":f"] == {"S": DUE}
    assert values[":empty"] == {"M": {}}


def test_scheduler_failure_does_not_mark_resolved(portal):
    portal._scheduler.create_schedule.side_effect = ClientError({"Error": {"Code": "AccessDeniedException"}}, "CreateSchedule")
    with pytest.raises(ClientError):
        portal.update_status({"arguments": {"id": "i1", "status": "resolved"}}, {"groups": {"official"}, "name": "Staff"})
    portal._ddb.update_item.assert_not_called()


def test_reopened_incident_is_rendered_as_open_by_portal(portal):
    view = portal.to_incident({"incident_id": {"S": "i1"}, "status": {"S": "OPEN"}})
    assert view["status"] == "received"
    assert view["followUpPending"] is False


def test_agent_tool_binds_subject_and_generation_to_current_turn(monkeypatch):
    strands = Mock()
    strands.tool = lambda fn: fn
    with patch.dict(sys.modules, {"strands": strands, "strands.models.bedrock": Mock(), "strands.types.exceptions": Mock()}):
        agent = load("agent_follow_up_tests", "modules/agent/src/agent/handler.py")
    agent.TOOL_FOLLOW_UP_FN = "follow-up"
    agent._invoke_tool = Mock(return_value={"ok": True})
    agent._turn.update(user_id=SENDER, follow_ups=[{"incident_id": "i1", "due_at": DUE}])
    assert agent.respond_follow_up("i1", "reopen") == {"ok": True}
    agent._invoke_tool.assert_called_once_with("follow-up", {"action": "respond", "user_id": SENDER, "incident_id": "i1", "decision": "reopen", "due_at": DUE})
    agent._invoke_tool.reset_mock()
    assert agent.respond_follow_up("other", "confirm")["ok"] is False
    agent._turn["consent_pending"] = True
    assert agent.respond_follow_up("i1", "confirm")["ok"] is False
    agent._invoke_tool.assert_not_called()
