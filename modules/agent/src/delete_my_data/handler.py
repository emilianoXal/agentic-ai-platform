"""Delete a citizen's personal data while preserving incident reports."""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

USERS_TABLE = os.environ.get("USERS_TABLE", "")
PLACES_TABLE = os.environ.get("PLACES_TABLE", "")
REPORTS_TABLE = os.environ.get("REPORTS_TABLE", "")
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
REPORTS_USER_INDEX = os.environ.get("REPORTS_USER_INDEX", "by-user")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
CONVERSATION_HISTORY_TABLE = os.environ.get("CONVERSATION_HISTORY_TABLE", "")
AGENTCORE_MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID", "")
AGENTCORE_IDENTITY_SECRET_ARN = os.environ.get("AGENTCORE_IDENTITY_SECRET_ARN", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_ddb = boto3.client("dynamodb")
_agentcore = boto3.client("bedrock-agentcore")
_secrets = boto3.client("secretsmanager")

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


_ERASURE_MARGIN_MS = 5000


class _MemoryErasureIncomplete(Exception):
    pass


def _ensure_time(context):
    if context is not None and (
        context.get_remaining_time_in_millis() < _ERASURE_MARGIN_MS
    ):
        raise _MemoryErasureIncomplete()


def _paginate(context, method, items_key, **kwargs):
    items = []
    while True:
        _ensure_time(context)
        response = method(**kwargs)
        items.extend(response.get(items_key, []))
        token = response.get("nextToken")
        if not token:
            return items
        kwargs["nextToken"] = token


def _erase_history(user_id, context):
    if not CONVERSATION_HISTORY_TABLE:
        return 0
    secret = _secrets.get_secret_value(SecretId=AGENTCORE_IDENTITY_SECRET_ARN)
    key = hmac.new(secret["SecretString"].encode("utf-8"),
                   user_id.encode("utf-8"), hashlib.sha256).hexdigest()
    items = _query_all(
        TableName=CONVERSATION_HISTORY_TABLE,
        KeyConditionExpression="citizen_id = :c",
        ExpressionAttributeValues={":c": {"S": key}},
        ProjectionExpression="citizen_id, #ts",
        ExpressionAttributeNames={"#ts": "ts"},
        ConsistentRead=True,
    )
    for item in items:
        _ensure_time(context)
        _ddb.delete_item(TableName=CONVERSATION_HISTORY_TABLE,
                         Key={"citizen_id": item["citizen_id"], "ts": item["ts"]})
    return len(items)


def _erase_memory(user_id, context):
    """Delete the citizen's AgentCore Memory events and memory records.

    Uses the same HMAC-derived actor/session ids as the agent Lambda.
    """
    _erase_history(user_id, context)
    if not AGENTCORE_MEMORY_ID:
        return 0, 0
    secret = _secrets.get_secret_value(SecretId=AGENTCORE_IDENTITY_SECRET_ARN)
    key = hmac.new(
        secret["SecretString"].encode("utf-8"), user_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    actor_id = f"citizen-{key}"
    session_id = f"conversation-{key}"

    events = _paginate(
        context, _agentcore.list_events, "events",
        memoryId=AGENTCORE_MEMORY_ID, actorId=actor_id, sessionId=session_id,
        includePayloads=False,
    )
    for event in events:
        _ensure_time(context)
        _agentcore.delete_event(
            memoryId=AGENTCORE_MEMORY_ID, actorId=actor_id,
            sessionId=session_id, eventId=event["eventId"],
        )

    records = [
        record for record in _paginate(
            context, _agentcore.list_memory_records, "memoryRecordSummaries",
            memoryId=AGENTCORE_MEMORY_ID, namespace="/",
        )
        if any(key in namespace for namespace in record.get("namespaces", []))
    ]
    for start in range(0, len(records), 100):
        _ensure_time(context)
        result = _agentcore.batch_delete_memory_records(
            memoryId=AGENTCORE_MEMORY_ID,
            records=[{"memoryRecordId": record["memoryRecordId"]}
                     for record in records[start:start + 100]],
        )
        if result.get("failedRecords"):
            raise _MemoryErasureIncomplete()
    return len(events), len(records)


def _audit(user_hash, places_deleted, reports_anonymized, memory_erased):
    _ddb.put_item(
        TableName=AUDIT_TABLE,
        Item={
            "entity_id": {"S": "privacy-deletion#" + user_hash},
            "ts": {"S": _now_iso()},
            "kind": {"S": "delete_my_data"},
            "subject_hash": {"S": user_hash},
            "places_deleted": {"N": str(places_deleted)},
            "reports_anonymized": {"N": str(reports_anonymized)},
            "memory_erased": {"BOOL": memory_erased},
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
            "message": "Please explicitly confirm that you want to delete your data.",
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
        try:
            memory_events, memory_records = _erase_memory(user_id, context)
            memory_erased = True
        except (ClientError, BotoCoreError, KeyError, _MemoryErasureIncomplete) as exc:
            memory_erased = False
            error_code = (exc.response.get("Error", {}).get("Code")
                          if isinstance(exc, ClientError) else type(exc).__name__)
            _log(logging.ERROR, "agentcore_memory_erasure_failed",
                 subject_hash=user_hash, error_code=error_code)
        _audit(user_hash, places_deleted, reports_anonymized, memory_erased)
        if not memory_erased:
            return {
                "ok": False,
                "error": "memory_erasure_failed",
                "places_deleted": places_deleted,
                "reports_anonymized": reports_anonymized,
                "message": "Your personal data was deleted, but the conversation "
                           "history could not be deleted yet. Please try again "
                           "later.",
            }
        _log(
            logging.INFO,
            "personal_data_deleted",
            subject_hash=user_hash,
            places_deleted=places_deleted,
            reports_anonymized=reports_anonymized,
            memory_events_deleted=memory_events,
            memory_records_deleted=memory_records,
        )
        return {
            "ok": True,
            "places_deleted": places_deleted,
            "reports_anonymized": reports_anonymized,
            "memory_events_deleted": memory_events,
            "memory_records_deleted": memory_records,
        }
    except ClientError:
        logger.exception(json.dumps({
            "event": "personal_data_deletion_failed",
            "subject_hash": user_hash,
        }))
        return {"ok": False, "error": "internal"}
