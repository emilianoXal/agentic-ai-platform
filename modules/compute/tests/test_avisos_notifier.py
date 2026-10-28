"""Citizen status notices: English, portal folio, one send per incident+status."""

import importlib.util
import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[3]
INCIDENT_ID = "a20ff770-7c52-4f85-bfe3-cb395ac0d15a"
FOLIO = "UB-2026-A20FF7"
SENDER = "5215511127271"
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    with patch("boto3.client"):
        spec.loader.exec_module(module)
    return module


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for key, value in {
        "USERS_TABLE": "users",
        "PLACES_TABLE": "places",
        "AUDIT_TABLE": "audit",
        "INCIDENTS_TABLE": "incidents",
        "OUTBOUND_FUNCTION_NAME": "outbound",
        "OUTBOUND_ORIGINATION_PHONE_NUMBER_ID": "phone-number-id-test",
    }.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        for table, key in (("users", "user_id"), ("places", "place_id"),
                           ("incidents", "incident_id")):
            ddb.create_table(
                TableName=table, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
            )
        ddb.create_table(
            TableName="audit", BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "entity_id", "KeyType": "HASH"},
                {"AttributeName": "ts", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "entity_id", "AttributeType": "S"},
                {"AttributeName": "ts", "AttributeType": "S"},
            ],
        )
        ddb.put_item(TableName="users", Item={
            "user_id": {"S": SENDER}, "consent": {"BOOL": True},
            "phone": {"S": SENDER},
        })
        ddb.put_item(TableName="incidents", Item={
            "incident_id": {"S": INCIDENT_ID},
            "status": {"S": "in_progress"},
            "created_at": {"S": "2026-10-28T11:00:00+00:00"},
        })
        handler = load("avisos_notifier", "modules/compute/src/notifier/handler.py")
        handler.USERS_TABLE = "users"
        handler.PLACES_TABLE = "places"
        handler.AUDIT_TABLE = "audit"
        handler.INCIDENTS_TABLE = "incidents"
        handler.OUTBOUND_FUNCTION_NAME = "outbound"
        handler.OUTBOUND_ORIGINATION_PHONE_NUMBER_ID = "phone-number-id-test"
        handler._ddb = ddb
        handler._lambda = Mock()
        handler._lambda.invoke.return_value = {"StatusCode": 202}
        yield handler


def _event(status="in_progress", source="urbanbot.dashboard", extra=None):
    detail = {
        "incident_id": INCIDENT_ID,
        "status": status,
        "user_ids": [SENDER],
        "source": "dashboard",
    }
    if extra:
        detail.update(extra)
    return {"source": source, "detail-type": "StatusChanged", "detail": detail}


def _payloads(app):
    texts = []
    for call in app._lambda.invoke.call_args_list:
        payload = json.loads(call.kwargs["Payload"])
        texts.append(payload["text"])
    return texts


def test_in_progress_notice_uses_english_folio_and_concrete_change(app):
    result = app.lambda_handler(_event("in_progress"), None)
    assert result["sent"] == 1
    text = _payloads(app)[0]
    assert text == "Your report UB-2026-A20FF7 is now In progress."
    assert FOLIO in text
    assert UUID_RE.search(text) is None
    assert "¿" not in text
    assert "quedó" not in text.lower()


def test_same_status_change_sends_once(app):
    first = app.lambda_handler(_event("in_progress"), None)
    second = app.lambda_handler(_event("in_progress"), None)
    assert first["sent"] == 1
    assert second["sent"] == 0
    assert second["skipped"] == 1
    assert app._lambda.invoke.call_count == 1


def test_later_status_still_notifies(app):
    app.lambda_handler(_event("sent_to_agency"), None)
    app.lambda_handler(_event("in_progress"), None)
    texts = _payloads(app)
    assert texts == [
        "Your report UB-2026-A20FF7 is now Sent to the agency.",
        "Your report UB-2026-A20FF7 is now In progress.",
    ]


def test_resolved_is_left_to_follow_up(app):
    result = app.lambda_handler(_event("resolved"), None)
    assert result["sent"] == 0
    app._lambda.invoke.assert_not_called()


def test_agent_route_event_without_status_uses_sent_to_agency(app):
    event = {
        "source": "urbanbot.agent",
        "detail-type": "StatusChanged",
        "detail": {"incident_id": INCIDENT_ID, "user_ids": [SENDER]},
    }
    result = app.lambda_handler(event, None)
    assert result["sent"] == 1
    assert _payloads(app)[0] == "Your report UB-2026-A20FF7 is now Sent to the agency."
    assert UUID_RE.search(_payloads(app)[0]) is None
