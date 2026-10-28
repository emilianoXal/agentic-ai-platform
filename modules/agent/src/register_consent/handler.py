"""urbanbot register_consent tool Lambda.

Persists the citizen's opt-in on the users table under the same user_id the
ingest Lambda reads. The model decides from free text whether to call this
tool; this handler only writes consent BOOL true and the timestamp.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

USERS_TABLE = os.environ.get("USERS_TABLE", "")
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


def _storage_user_id(user_id):
    raw = str(user_id).strip()
    if raw.startswith("+"):
        return raw[1:]
    return raw


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    user_id = event.get("user_id")
    stored = _storage_user_id(user_id) if user_id else ""
    if not stored:
        _log(logging.WARNING, "invalid_input")
        return {"ok": False, "error": "invalid_input"}

    now = _now_iso()
    try:
        _ddb.update_item(
            TableName=USERS_TABLE,
            Key={"user_id": {"S": stored}},
            UpdateExpression="SET #c = :t, consent_at = :ts",
            ExpressionAttributeNames={"#c": "consent"},
            ExpressionAttributeValues={
                ":t": {"BOOL": True},
                ":ts": {"S": now},
            },
        )
    except ClientError:
        logger.exception(json.dumps({
            "event": "register_consent_failed",
            "user_hash": _hash_id(stored),
        }))
        return {"ok": False, "error": "internal"}

    _log(logging.INFO, "consent_registered", user_hash=_hash_id(stored))
    return {"ok": True, "consent": True, "consent_at": now}
