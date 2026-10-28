"""Behavior tests for the personal-data deletion Lambda."""

import importlib.util
import os
from pathlib import Path
from unittest import mock

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
        }
        self.incidents = {
            "incident-1": {
                "incident_id": {"S": "incident-1"},
                "report_count": {"N": "1"},
                "subscribers": {"SS": ["5215512345678", "5215500000000"]},
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
                {"report_id": item["report_id"], "incident_id": item["incident_id"]}
                for item in self.reports.values()
                if item.get("user_id", {}).get("S") == user_id
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

    assert result == {"ok": True, "places_deleted": 1, "reports_anonymized": 1}
    assert database.users == {}
    assert database.places == {}
    assert database.reports["report-1"] == {
        "report_id": {"S": "report-1"},
        "incident_id": {"S": "incident-1"},
    }
    assert database.incidents["incident-1"]["report_count"] == {"N": "1"}
    assert database.incidents["incident-1"]["subscribers"] == {"SS": ["5215500000000"]}
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
    }


def test_delete_requires_explicit_confirmation_without_writes():
    handler._ddb = mock.MagicMock()

    result = handler.lambda_handler({"user_id": "5215512345678"}, None)

    assert result["error"] == "confirmation_required"
    handler._ddb.query.assert_not_called()
    handler._ddb.delete_item.assert_not_called()
    handler._ddb.update_item.assert_not_called()
    handler._ddb.put_item.assert_not_called()
