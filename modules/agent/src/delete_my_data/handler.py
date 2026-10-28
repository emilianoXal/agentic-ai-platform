"""Delete a citizen's personal data while preserving incident reports."""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

USERS_TABLE = os.environ.get("USERS_TABLE", "")
PLACES_TABLE = os.environ.get("PLACES_TABLE", "")
REPORTS_TABLE = os.environ.get("REPORTS_TABLE", "")
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
REPORTS_USER_INDEX = os.environ.get("REPORTS_USER_INDEX", "by-user")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_ddb = boto3.client("dynamodb")

logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


def _log(level, event, **fields):
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, default=str))


def _hash_id(value):
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _query_all(**kwargs):
    items = []
    while True:
        response = _ddb.query(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def _delete_places(user_id):
    places = _query_all(
        TableName=PLACES_TABLE,
        KeyConditionExpression="user_id = :u",
        ExpressionAttributeValues={":u": {"S": user_id}},
        ProjectionExpression="user_id, place_id",
    )
    for place in places:
        _ddb.delete_item(
            TableName=PLACES_TABLE,
            Key={
                "user_id": place["user_id"],
                "place_id": place["place_id"],
            },
        )
    return len(places)


def _scan_subscribed_incidents(user_id):
    kwargs = {
        "TableName": INCIDENTS_TABLE,
        "FilterExpression": "contains(subscribers, :u)",
        "ExpressionAttributeValues": {":u": {"S": user_id}},
        "ProjectionExpression": "incident_id",
    }
    items = []
    while True:
        response = _ddb.scan(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return [item["incident_id"]["S"] for item in items]
        kwargs["ExclusiveStartKey"] = last_key


def _unsubscribe_incidents(user_id):
    for incident_id in _scan_subscribed_incidents(user_id):
        _unsubscribe(incident_id, user_id)


def _unsubscribe(incident_id, user_id):
    try:
        _ddb.update_item(
            TableName=INCIDENTS_TABLE,
            Key={"incident_id": {"S": incident_id}},
            UpdateExpression="DELETE subscribers :sub",
            ConditionExpression="attribute_exists(incident_id)",
            ExpressionAttributeValues={":sub": {"SS": [user_id]}},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise


def _anonymize_reports(user_id):
    reports = _query_all(
        TableName=REPORTS_TABLE,
        IndexName=REPORTS_USER_INDEX,
        KeyConditionExpression="user_id = :u",
        ExpressionAttributeValues={":u": {"S": user_id}},
        ProjectionExpression="report_id",
    )
    personal_fields = {
        "#user_id": "user_id",
        "#phone": "phone",
        "#phone_number": "phone_number",
        "#telefono": "telefono",
    }
    for report in reports:
        _ddb.update_item(
            TableName=REPORTS_TABLE,
            Key={"report_id": report["report_id"]},
            UpdateExpression="REMOVE " + ", ".join(personal_fields),
            ExpressionAttributeNames=personal_fields,
        )
    return len(reports)


def _audit(user_hash, places_deleted, reports_anonymized):
    _ddb.put_item(
        TableName=AUDIT_TABLE,
        Item={
            "entity_id": {"S": "privacy-deletion#" + user_hash},
            "ts": {"S": _now_iso()},
            "kind": {"S": "delete_my_data"},
            "subject_hash": {"S": user_hash},
            "places_deleted": {"N": str(places_deleted)},
            "reports_anonymized": {"N": str(reports_anonymized)},
        },
    )


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    user_id = event.get("user_id")
    confirmed = event.get("confirmed") is True
    if not user_id:
        return {"ok": False, "error": "invalid_input"}
    if not confirmed:
        return {
            "ok": False,
            "error": "confirmation_required",
            "message": "Confirma explicitamente que deseas borrar tus datos.",
        }

    user_id = str(user_id)
    user_hash = _hash_id(user_id)
    try:
        _unsubscribe_incidents(user_id)
        reports_anonymized = _anonymize_reports(user_id)
        places_deleted = _delete_places(user_id)
        _ddb.delete_item(
            TableName=USERS_TABLE,
            Key={"user_id": {"S": user_id}},
        )
        _audit(user_hash, places_deleted, reports_anonymized)
        _log(
            logging.INFO,
            "personal_data_deleted",
            subject_hash=user_hash,
            places_deleted=places_deleted,
            reports_anonymized=reports_anonymized,
        )
        return {
            "ok": True,
            "places_deleted": places_deleted,
            "reports_anonymized": reports_anonymized,
        }
    except ClientError:
        logger.exception(json.dumps({
            "event": "personal_data_deletion_failed",
            "subject_hash": user_hash,
        }))
        return {"ok": False, "error": "internal"}
