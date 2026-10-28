"""urbanbot get_status tool Lambda.

Agent tool: return the current status + last-updated of a report (or all of a
user's reports) plus the parent incident status (RF-16). Passes through the six
statuses Recibido / Enviado a dependencia / En atencion / Resuelto / No procede /
Reabierto (RF-17). Read-only; emits a light access log only.

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
REPORTS_TABLE = os.environ.get("REPORTS_TABLE", "")
REPORTS_USER_INDEX = os.environ.get("REPORTS_USER_INDEX", "by-user")
INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE", "")
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "20"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- Clients created at module load (reused across warm invocations) ---------
_ddb = boto3.client("dynamodb")

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


def _incident_status(incident_id):
    """Read the parent incident status (best-effort; None if missing)."""
    if not incident_id:
        return None
    resp = _ddb.get_item(
        TableName=INCIDENTS_TABLE,
        Key={"incident_id": {"S": incident_id}},
        ProjectionExpression="#s, updated_at",
        ExpressionAttributeNames={"#s": "status"},
    )
    item = resp.get("Item")
    if not item:
        return None
    return item.get("status", {}).get("S")


def _report_view(item):
    """Compact status view of a report row + parent incident status."""
    incident_id = item.get("incident_id", {}).get("S")
    return {
        "report_id": item.get("report_id", {}).get("S"),
        "category": item.get("category", {}).get("S"),
        "status": item.get("status", {}).get("S"),
        "incident_id": incident_id,
        "incident_status": _incident_status(incident_id),
        "updated_at": item.get("updated_at", {}).get("S"),
    }


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    user_id = event.get("user_id")
    report_id = event.get("report_id")

    if not user_id and not report_id:
        _log(logging.WARNING, "invalid_input", reason="missing_user_and_report")
        return {"ok": False, "error": "invalid_input",
                "message": "Proporciona report_id o user_id."}

    try:
        if report_id:
            resp = _ddb.get_item(
                TableName=REPORTS_TABLE,
                Key={"report_id": {"S": report_id}},
            )
            item = resp.get("Item")
            if not item:
                return {"ok": False, "error": "not_found",
                        "message": "No se encontro el reporte."}
            # Access control: if user_id given, it must own the report.
            if user_id and item.get("user_id", {}).get("S") != str(user_id):
                _log(logging.WARNING, "access_denied",
                     user=_mask_phone(user_id), report_id=report_id)
                return {"ok": False, "error": "not_found",
                        "message": "No se encontro el reporte."}
            _log(logging.INFO, "status_read", report_id=report_id,
                 user=_mask_phone(user_id))
            return {"ok": True, "report": _report_view(item)}

        resp = _ddb.query(
            TableName=REPORTS_TABLE,
            IndexName=REPORTS_USER_INDEX,
            KeyConditionExpression="user_id = :u",
            ExpressionAttributeValues={":u": {"S": str(user_id)}},
            ScanIndexForward=False,
            Limit=MAX_RESULTS,
        )
        reports = [_report_view(i) for i in resp.get("Items", [])]
        _log(logging.INFO, "status_list", user=_mask_phone(user_id),
             user_hash=_hash_id(user_id), count=len(reports))
        return {"ok": True, "reports": reports}
    except ClientError:
        logger.exception(json.dumps({"event": "get_status_failed",
                                     "user": _mask_phone(user_id)}))
        return {"ok": False, "error": "internal"}
