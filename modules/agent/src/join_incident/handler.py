"""urbanbot join_incident tool Lambda.

Agent tool: attach a report to an existing OPEN incident (RF-29 explicit attach
path, RF-10 subscribers). incident_id is always required, plus exactly one of:
(a) report_id -> attach an existing report; or
(b) user_id + category + geohash -> create a report first, then attach it.
report_id wins if both are supplied. Branch (b) trusts the caller's incident_id
and does NOT re-check geohash/category equality (by design). Recomputes priority
= f(report_count, max severity) (RF-30). Writes an audit-log entry (RF-15).

Stdlib + boto3 only (bundled in the python3.12 Lambda runtime).
"""

import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# --- Config from environment -------------------------------------------------
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
REPORTS_TABLE = os.environ.get("REPORTS_TABLE", "")
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "")
PENDING_MEDIA_TABLE = os.environ.get("PENDING_MEDIA_TABLE", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Clients created at module load (reused across warm invocations) ---------
_ddb = boto3.client("dynamodb")

# --- Structured JSON-line logger (PII-masking; mirrors compute/ingest) -------
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


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


def _portal_folio(incident_id, created_at=""):
    year = created_at[:4] if len(created_at) >= 4 and created_at[:4].isdigit() else str(
        datetime.now(timezone.utc).year)
    token = (incident_id or "??????")[:6].upper()
    return "UB-{}-{}".format(year, token)


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


def _priority(report_count, max_severity):
    """Recompute priority = f(report_count, max severity) (RF-30)."""
    sev_rank = _SEVERITY_RANK.get(str(max_severity).lower(), 1)
    return report_count + (sev_rank * 2)


def _sanitized_media(media):
    if not isinstance(media, list):
        return []
    return [value for value in media if isinstance(value, str) and value.startswith("sanitized/")]


def _consume_pending_media(user_id):
    """Atomically take the citizen's unexpired pending sanitized keys."""
    if not PENDING_MEDIA_TABLE:
        return []
    try:
        resp = _ddb.delete_item(
            TableName=PENDING_MEDIA_TABLE,
            Key={"user_hash": {"S": hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()}},
            ReturnValues="ALL_OLD",
        )
    except ClientError:
        _log(logging.WARNING, "pending_media_consume_failed", user_hash=_hash_id(user_id))
        return []
    now = int(time.time())
    pending = [
        (int(value["N"]), key)
        for key, value in resp.get("Attributes", {}).items()
        if key.startswith("sanitized/") and "N" in value and int(value["N"]) > now
    ]
    return [key for _, key in sorted(pending)]


def _create_report(user_id, category, geohash, media):
    """Create a minimal report row for the create-then-attach branch (b)."""
    report_id = str(uuid.uuid4())
    now = _now_iso()
    item = {
        "report_id": {"S": report_id},
        "user_id": {"S": str(user_id)},
        "category": {"S": category},
        "geohash": {"S": geohash},
        "status": {"S": "Recibido"},
        "created_at": {"S": now},
        "updated_at": {"S": now},
    }
    media = list(dict.fromkeys(_sanitized_media(media) + _consume_pending_media(user_id)))
    if media:
        item["media"] = {"L": [{"S": key} for key in media]}
    _ddb.put_item(TableName=REPORTS_TABLE, Item=item)
    return report_id, len(media)


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    incident_id = event.get("incident_id")
    report_id = event.get("report_id")
    user_id = event.get("user_id")
    category = event.get("category")
    geohash = event.get("geohash")
    severity = event.get("severity")

    if not incident_id:
        _log(logging.WARNING, "invalid_input", reason="missing_incident_id")
        return {"ok": False, "error": "invalid_input",
                "message": "incident_id is required."}

    has_create_triple = bool(user_id and category and geohash)
    if not report_id and not has_create_triple:
        _log(logging.WARNING, "invalid_input", reason="no_branch")
        return {"ok": False, "error": "invalid_input",
                "message": "Provide report_id or user_id+category+geohash."}

    try:
        created = False
        created_photos = 0
        if not report_id:
            # Branch (b): create then attach. Trusts incident_id; does NOT
            # re-check geohash/category equality against the incident.
            report_id, created_photos = _create_report(
                user_id, category, geohash, event.get("media"))
            created = True

        subscriber = str(user_id) if user_id else None
        add_expr = "ADD report_count :one"
        values = {
            ":one": {"N": "1"},
            ":now": {"S": _now_iso()},
            ":rid": {"L": [{"S": report_id}]},
            ":empty": {"L": []},
            ":open": {"S": "OPEN"},
        }
        if created_photos:
            add_expr += ", photo_count :photos"
            values[":photos"] = {"N": str(int(created_photos))}
        update_expr = (
            add_expr
            + (" , subscribers :sub" if subscriber else "")
            + " SET updated_at = :now, report_ids = "
            "list_append(if_not_exists(report_ids, :empty), :rid)"
        )
        if subscriber:
            values[":sub"] = {"SS": [subscriber]}

        resp = _ddb.update_item(
            TableName=INCIDENTS_TABLE,
            Key={"incident_id": {"S": incident_id}},
            UpdateExpression=update_expr,
            ConditionExpression="attribute_exists(incident_id) AND #s = :open",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )

        attrs = resp.get("Attributes", {})
        report_count = int(attrs.get("report_count", {}).get("N", "1"))
        max_sev = severity or attrs.get("max_severity", {}).get("S")
        priority = _priority(report_count, max_sev)

        _ddb.update_item(
            TableName=INCIDENTS_TABLE,
            Key={"incident_id": {"S": incident_id}},
            UpdateExpression="SET priority = :p",
            ExpressionAttributeValues={":p": {"N": str(priority)}},
        )

        _audit(
            "incident#" + incident_id,
            "join_incident",
            user_hash=_hash_id(user_id),
            report_id=report_id,
            created=str(created),
        )

        _log(
            logging.INFO,
            "incident_joined",
            incident_id=incident_id,
            report_id=report_id,
            user=_mask_phone(user_id),
            user_hash=_hash_id(user_id),
            report_count=report_count,
            priority=priority,
            created=created,
        )
        return {
            "ok": True,
            "folio": _portal_folio(incident_id, attrs.get("created_at", {}).get("S", "")),
            "incident_id": incident_id,
            "report_id": report_id,
            "report_count": report_count,
            "priority": priority,
        }
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            _log(logging.WARNING, "incident_not_joinable", incident_id=incident_id)
            return {"ok": False, "error": "incident_not_joinable",
                    "message": "The incident does not exist or is not open."}
        logger.exception(json.dumps({"event": "join_incident_failed",
                                     "incident_id": incident_id}))
        return {"ok": False, "error": "internal"}
