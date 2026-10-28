"""create_report and get_status expose the portal short folio, never as the citizen id."""

import importlib.util
import re
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[3]
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
FOLIO_RE = re.compile(r"^UB-\d{4}-[A-Z0-9]{6}$")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    with patch("boto3.client"):
        spec.loader.exec_module(module)
    return module


@pytest.fixture
def tables(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for key, value in {
        "REPORTS_TABLE": "reports",
        "INCIDENTS_TABLE": "incidents",
        "AUDIT_TABLE": "audit",
        "PENDING_MEDIA_TABLE": "",
        "REPORTS_USER_INDEX": "by-user",
    }.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="reports", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "report_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "report_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "by-user",
                "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
        )
        ddb.create_table(
            TableName="incidents", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "incident_id", "AttributeType": "S"},
                {"AttributeName": "geohash", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "by-geohash",
                "KeySchema": [{"AttributeName": "geohash", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
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
        yield ddb


def test_create_report_confirmation_returns_portal_folio(tables, monkeypatch):
    monkeypatch.setenv("REPORTS_TABLE", "reports")
    monkeypatch.setenv("INCIDENTS_TABLE", "incidents")
    monkeypatch.setenv("AUDIT_TABLE", "audit")
    handler = load("avisos_create_report", "modules/agent/src/create_report/handler.py")
    handler._ddb = tables
    handler.REPORTS_TABLE = "reports"
    handler.INCIDENTS_TABLE = "incidents"
    handler.AUDIT_TABLE = "audit"
    handler.PENDING_MEDIA_TABLE = ""
    result = handler.lambda_handler({
        "user_id": "5215511127271",
        "category": "agua",
        "geohash": "9g3qrbc",
        "description": "fuga en la esquina",
    }, None)
    assert result["ok"] is True
    assert FOLIO_RE.match(result["folio"])
    assert result["folio"] == handler._portal_folio(
        result["incident_id"], result.get("created_at", ""))
    token = result["incident_id"][:6].upper()
    assert result["folio"].endswith("-" + token)
    assert result["folio"] != result["incident_id"]
    assert result["folio"] != result["report_id"]


def test_get_status_lists_folio_not_as_the_citizen_label(tables, monkeypatch):
    monkeypatch.setenv("REPORTS_TABLE", "reports")
    monkeypatch.setenv("INCIDENTS_TABLE", "incidents")
    monkeypatch.setenv("REPORTS_USER_INDEX", "by-user")
    incident_id = "a20ff770-7c52-4f85-bfe3-cb395ac0d15a"
    tables.put_item(TableName="incidents", Item={
        "incident_id": {"S": incident_id},
        "status": {"S": "in_progress"},
        "created_at": {"S": "2026-10-28T11:00:00+00:00"},
    })
    tables.put_item(TableName="reports", Item={
        "report_id": {"S": "r-citizen"},
        "user_id": {"S": "5215511127271"},
        "incident_id": {"S": incident_id},
        "category": {"S": "agua"},
        "status": {"S": "En atencion"},
        "updated_at": {"S": "2026-10-28T12:00:00+00:00"},
    })
    handler = load("avisos_get_status", "modules/agent/src/get_status/handler.py")
    handler._ddb = tables
    handler.REPORTS_TABLE = "reports"
    handler.INCIDENTS_TABLE = "incidents"
    handler.REPORTS_USER_INDEX = "by-user"
    result = handler.lambda_handler({"user_id": "5215511127271"}, None)
    assert result["ok"] is True
    view = result["reports"][0]
    assert view["folio"] == "UB-2026-A20FF7"
    assert UUID_RE.search(view["folio"]) is None
