"""Follow-up citizen notice: English, portal folio, no UUID."""

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
DUE = "2026-10-28T16:02:00+00:00"
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
        "INCIDENTS_TABLE": "incidents",
        "REPORTS_TABLE": "reports",
        "USERS_TABLE": "users",
        "AUDIT_TABLE": "audit",
        "OUTBOUND_FUNCTION_NAME": "outbound",
        "OUTBOUND_ORIGINATION_PHONE_NUMBER_ID": "phone-number-id-test",
    }.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        for table, key in (("incidents", "incident_id"), ("reports", "report_id"),
                           ("users", "user_id")):
            spec = dict(
                TableName=table,
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            if table == "reports":
                spec["AttributeDefinitions"].append(
                    {"AttributeName": "user_id", "AttributeType": "S"})
                spec["GlobalSecondaryIndexes"] = [{
                    "IndexName": "by-user",
                    "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }]
            ddb.create_table(**spec)
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
        ddb.put_item(TableName="incidents", Item={
            "incident_id": {"S": INCIDENT_ID},
            "status": {"S": "resolved"},
            "category": {"S": "agua"},
            "created_at": {"S": "2026-10-28T11:00:00+00:00"},
            "follow_up_due_at": {"S": DUE},
            "follow_up_deliveries": {"M": {}},
            "report_ids": {"L": [{"S": "r1"}]},
        })
        ddb.put_item(TableName="reports", Item={
            "report_id": {"S": "r1"},
            "incident_id": {"S": INCIDENT_ID},
            "user_id": {"S": SENDER},
            "status": {"S": "Resuelto"},
        })
        ddb.put_item(TableName="users", Item={
            "user_id": {"S": SENDER}, "consent": {"BOOL": True},
        })
        handler = load("avisos_follow_up", "modules/follow_up/src/handler.py")
        handler._ddb = ddb
        handler._lambda = Mock()
        handler._lambda.invoke.side_effect = lambda **kw: {
            "Payload": __import__("io").BytesIO(b'{"ok":true}')
        }
        yield handler


def test_follow_up_notice_is_english_with_portal_folio(app):
    result = app.lambda_handler(
        {"action": "send", "incident_id": INCIDENT_ID, "due_at": DUE}, None)
    assert result == {"ok": True, "sent": 1}
    payload = json.loads(app._lambda.invoke.call_args.kwargs["Payload"])
    text = payload["text"]
    assert text == (
        "Your report UB-2026-A20FF7 was marked resolved by the agency. "
        "Is it fixed? Tell me in your own words."
    )
    assert FOLIO in text
    assert UUID_RE.search(text) is None
    assert INCIDENT_ID not in text
    assert "¿" not in text
    assert "dependencia" not in text.lower()
