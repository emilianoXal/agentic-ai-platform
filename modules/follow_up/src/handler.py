"""Scheduled citizen follow-ups and sender-scoped resolution decisions."""

import hashlib
import json
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

INCIDENTS = os.environ["INCIDENTS_TABLE"]
REPORTS = os.environ["REPORTS_TABLE"]
USERS = os.environ["USERS_TABLE"]
AUDIT = os.environ["AUDIT_TABLE"]
OUTBOUND = os.environ["OUTBOUND_FUNCTION_NAME"]
ORIGINATION = os.environ.get("OUTBOUND_ORIGINATION_PHONE_NUMBER_ID", "")
_ddb = boto3.client("dynamodb")
_lambda = boto3.client("lambda")


def _s(item, key):
    return item.get(key, {}).get("S", "")


def _portal_folio(incident_id, created_at=""):
    year = created_at[:4] if len(created_at) >= 4 and created_at[:4].isdigit() else str(
        datetime.now(timezone.utc).year)
    token = (incident_id or "??????")[:6].upper()
    return "UB-{}-{}".format(year, token)


def _follow_up_text(incident):
    incident_id = _s(incident, "incident_id")
    folio = _portal_folio(incident_id, _s(incident, "created_at"))
    return (
        "Your report {} was marked resolved by the agency. "
        "Is it fixed? Tell me in your own words."
    ).format(folio)


def _subject(user_id):
    return hashlib.sha256(user_id.encode()).hexdigest()


def _incident(incident_id):
    return _ddb.get_item(
        TableName=INCIDENTS, Key={"incident_id": {"S": incident_id}},
        ConsistentRead=True,
    ).get("Item", {})


def _reports(incident):
    for value in incident.get("report_ids", {}).get("L", []):
        report = _ddb.get_item(
            TableName=REPORTS, Key={"report_id": value}, ConsistentRead=True,
        ).get("Item", {})
        yield report


def _pending(user_id):
    incidents = {}
    request = dict(
        TableName=REPORTS, IndexName="by-user",
        KeyConditionExpression="user_id = :u",
        ExpressionAttributeValues={":u": {"S": user_id}},
    )
    while True:
        page = _ddb.query(**request)
        for report in page.get("Items", []):
            incident_id = _s(report, "incident_id")
            if incident_id and incident_id not in incidents:
                incidents[incident_id] = _incident(incident_id)
        if not page.get("LastEvaluatedKey"):
            break
        request["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    key = _subject(user_id)
    return [{"incident_id": iid, "category": _s(item, "category"),
             "due_at": _s(item, "follow_up_due_at")}
            for iid, item in incidents.items()
            if _s(item, "status") == "resolved"
            and item.get("follow_up_deliveries", {}).get("M", {}).get(key, {}).get("S") == "pending"]


def _send(event):
    incident_id, due_at = event["incident_id"], event["due_at"]
    item = _incident(incident_id)
    if _s(item, "status") != "resolved" or _s(item, "follow_up_due_at") != due_at:
        return {"ok": True, "skipped": "stale"}
    if not ORIGINATION:
        raise RuntimeError("follow_up_origination_missing")
    try:
        _ddb.update_item(
            TableName=INCIDENTS, Key={"incident_id": {"S": incident_id}},
            UpdateExpression="SET follow_up_ran = :due",
            ConditionExpression="#s = :resolved AND follow_up_due_at = :due",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":resolved": {"S": "resolved"}, ":due": {"S": due_at}},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {"ok": True, "skipped": "stale"}
        raise
    recipients = {_s(report, "user_id") for report in _reports(item)} - {""}
    sent = 0
    for user_id in recipients:
        user = _ddb.get_item(TableName=USERS, Key={"user_id": {"S": user_id}},
                             ConsistentRead=True).get("Item", {})
        if (not user or user.get("paused", {}).get("BOOL")
                or user.get("consent", {}).get("BOOL") is not True):
            continue
        key = _subject(user_id)
        names = {"#s": "status", "#k": key}
        values = {":resolved": {"S": "resolved"}, ":due": {"S": due_at},
                  ":sending": {"S": "sending"}, ":failed": {"S": "failed"}}
        try:
            _ddb.update_item(
                TableName=INCIDENTS, Key={"incident_id": {"S": incident_id}},
                UpdateExpression="SET follow_up_deliveries.#k = :sending",
                ConditionExpression="#s = :resolved AND follow_up_due_at = :due AND "
                                    "(attribute_not_exists(follow_up_deliveries.#k) OR follow_up_deliveries.#k = :failed)",
                ExpressionAttributeNames=names, ExpressionAttributeValues=values,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                continue
            raise
        # Reserve before calling the non-idempotent channel. An uncertain transport
        # outcome stays reserved: retrying it could send a duplicate to the citizen.
        response = _lambda.invoke(
            FunctionName=OUTBOUND, InvocationType="RequestResponse",
            Payload=json.dumps({
                "to": _s(user, "phone") or user_id,
                "text": _follow_up_text(item),
                "origination_phone_number_id": ORIGINATION,
            }).encode(),
        )
        result = json.loads(response["Payload"].read())
        if response.get("FunctionError") or not result.get("ok"):
            _ddb.update_item(
                TableName=INCIDENTS, Key={"incident_id": {"S": incident_id}},
                UpdateExpression="SET follow_up_deliveries.#k = :failed",
                ConditionExpression="follow_up_due_at = :due",
                ExpressionAttributeNames={"#k": key},
                ExpressionAttributeValues={":due": {"S": due_at}, ":failed": {"S": "failed"}},
            )
            raise RuntimeError("follow_up_send_failed")
        _ddb.update_item(
            TableName=INCIDENTS, Key={"incident_id": {"S": incident_id}},
            UpdateExpression="SET follow_up_deliveries.#k = :pending",
            ConditionExpression="follow_up_due_at = :due AND follow_up_deliveries.#k = :sending",
            ExpressionAttributeNames={"#k": key},
            ExpressionAttributeValues={":due": {"S": due_at}, ":sending": {"S": "sending"},
                                       ":pending": {"S": "pending"}},
        )
        sent += 1
    return {"ok": True, "sent": sent}


def _respond(event):
    user_id, incident_id, decision = event["user_id"], event["incident_id"], event["decision"]
    if decision not in ("confirm", "reopen"):
        return {"ok": False, "error": "invalid_decision"}
    if incident_id not in {entry["incident_id"] for entry in _pending(user_id)}:
        return {"ok": False, "error": "no_pending_follow_up"}
    now = datetime.now(timezone.utc).isoformat()
    names = {"#s": "status", "#k": _subject(user_id)}
    values = {":resolved": {"S": "resolved"}, ":pending": {"S": "pending"},
              ":decision": {"S": decision}, ":now": {"S": now},
              ":due": {"S": event["due_at"]}}
    expression = "SET follow_up_deliveries.#k = :decision, updated_at = :now"
    if decision == "reopen":
        expression += ", #s = :reopened REMOVE follow_up_due_at"
        values[":reopened"] = {"S": "reopened"}
    try:
        item = _ddb.update_item(
            TableName=INCIDENTS, Key={"incident_id": {"S": incident_id}},
            UpdateExpression=expression,
            ConditionExpression="#s = :resolved AND follow_up_due_at = :due AND follow_up_deliveries.#k = :pending",
            ExpressionAttributeNames=names, ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {"ok": False, "error": "stale_follow_up"}
        raise
    if decision == "reopen":
        for report_id in item.get("report_ids", {}).get("L", []):
            try:
                _ddb.update_item(
                    TableName=REPORTS, Key={"report_id": report_id},
                    UpdateExpression="SET #s = :s, updated_at = :now",
                    ConditionExpression="attribute_exists(report_id)",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": {"S": "Reabierto"}, ":now": {"S": now}},
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
    _ddb.put_item(TableName=AUDIT, Item={
        "entity_id": {"S": "incident#" + incident_id}, "ts": {"S": now},
        "kind": {"S": "citizen_reopened" if decision == "reopen" else "citizen_confirmed"},
    })
    return {"ok": True, "incident_id": incident_id,
            "status": "reopened" if decision == "reopen" else "resolved"}


def lambda_handler(event, context):
    action = event.get("action")
    if action == "pending" and event.get("user_id"):
        return {"ok": True, "pending": _pending(str(event["user_id"]))}
    if action == "send" and event.get("incident_id") and event.get("due_at"):
        return _send(event)
    if action == "respond" and all(event.get(k) for k in ("user_id", "incident_id", "decision", "due_at")):
        return _respond(event)
    return {"ok": False, "error": "invalid_input"}
