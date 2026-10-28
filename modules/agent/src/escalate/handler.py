"""urbanbot escalate tool Lambda.

Agent tool: escalate an incident when it crosses a threshold (RF-31). Thresholds
come from env: ESCALATE_REPORT_THRESHOLD (default 10) and ESCALATE_DAYS_THRESHOLD
(default 3). Reads the incident; if report_count or age-in-days is at/over the
threshold, conditionally transitions OPEN -> ESCALATED (writes an escalation
marker), writes an audit entry, and emits EXACTLY ONE EventBridge event
(detail-type "IncidentNearby", the string the compute notifier rule matches).
category + status in the event detail are read from the incident item in this
call (post-update status == ESCALATED). Returns whether/why it escalated.

Stdlib + boto3 only (bundled in the python3.12 Lambda runtime).
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# --- Config from environment -------------------------------------------------
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
EVENTS_BUS_NAME = os.environ.get("EVENTS_BUS_NAME", "")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
ESCALATE_REPORT_THRESHOLD = int(os.environ.get("ESCALATE_REPORT_THRESHOLD", "10"))
ESCALATE_DAYS_THRESHOLD = int(os.environ.get("ESCALATE_DAYS_THRESHOLD", "3"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Clients created at module load (reused across warm invocations) ---------
_ddb = boto3.client("dynamodb")
_events = boto3.client("events")

# --- Structured JSON-line logger (PII-masking; mirrors compute/ingest) -------
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


def _log(level, event, **fields):
    """Emit one structured JSON log line. Never logs raw PII."""
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, default=str))


def _mask_phone(value):
    """PII masking: keep only the last 4 digits of a phone/user id."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 4:
        return "****" + digits[-4:]
    return "****"


def _hash_id(value):
    """Stable, non-reversible id for correlating logs without exposing PII."""
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _audit(entity_id, kind, **extra):
    """Write a lightweight audit-log entry (entity_id + ts), RF-15."""
    item = {
        "entity_id": {"S": entity_id},
        "ts": {"S": _now_iso()},
        "kind": {"S": kind},
    }
    for key, val in extra.items():
        if val is not None:
            item[key] = {"S": str(val)}
    _ddb.put_item(TableName=AUDIT_TABLE, Item=item)


def _age_days(created_at):
    if not created_at:
        return 0
    try:
        when = datetime.fromisoformat(created_at)
    except ValueError:
        return 0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).days


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    incident_id = event.get("incident_id")
    reason = event.get("reason")
    user_ids = event.get("user_ids")

    if not incident_id:
        _log(logging.WARNING, "invalid_input", reason="missing_incident_id")
        return {"ok": False, "error": "invalid_input",
                "message": "incident_id is required."}

    try:
        resp = _ddb.get_item(
            TableName=INCIDENTS_TABLE,
            Key={"incident_id": {"S": incident_id}},
        )
        item = resp.get("Item")
        if not item:
            return {"ok": False, "error": "not_found",
                    "message": "Incident not found."}

        report_count = int(item.get("report_count", {}).get("N", "0"))
        age_days = _age_days(item.get("created_at", {}).get("S"))
        category = item.get("category", {}).get("S")

        over_threshold = (report_count >= ESCALATE_REPORT_THRESHOLD
                          or age_days >= ESCALATE_DAYS_THRESHOLD)
        if not over_threshold:
            _log(logging.INFO, "below_threshold", incident_id=incident_id,
                 report_count=report_count, age_days=age_days)
            return {"ok": True, "escalated": False, "reason": "below_threshold",
                    "status": item.get("status", {}).get("S")}

        now = _now_iso()
        try:
            _ddb.update_item(
                TableName=INCIDENTS_TABLE,
                Key={"incident_id": {"S": incident_id}},
                UpdateExpression="SET #s = :esc, escalated_at = :t, escalation_reason = :r",
                ConditionExpression="#s = :open",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":esc": {"S": "ESCALATED"},
                    ":open": {"S": "OPEN"},
                    ":t": {"S": now},
                    ":r": {"S": str(reason) if reason else "threshold"},
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                _log(logging.INFO, "already_escalated", incident_id=incident_id)
                return {"ok": True, "escalated": False,
                        "reason": "not_open", "status": "ESCALATED"}
            raise

        detail = {
            "incident_id": incident_id,
            "category": category,
            "status": "ESCALATED",
        }
        if user_ids:
            detail["user_ids"] = user_ids
        _events.put_events(
            Entries=[{
                "Source": "urbanbot.agent",
                "DetailType": "IncidentNearby",
                "Detail": json.dumps(detail, default=str),
                "EventBusName": EVENTS_BUS_NAME,
            }]
        )

        _audit(
            "incident#" + incident_id,
            "escalate",
            report_count=report_count,
            age_days=age_days,
            reason=reason,
        )
        _log(logging.INFO, "escalated", incident_id=incident_id,
             report_count=report_count, age_days=age_days, category=category)
        return {"ok": True, "escalated": True, "status": "ESCALATED",
                "report_count": report_count, "age_days": age_days}
    except ClientError:
        logger.exception(json.dumps({"event": "escalate_failed",
                                     "incident_id": incident_id}))
        return {"ok": False, "error": "internal"}
