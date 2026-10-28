#!/usr/bin/env python3
"""Smoke the urbanbot WhatsApp inbound path against the live dev account.

Publishes an AWS End User Messaging Social envelope to the inbound SNS topic
and checks ingest, consumer, agent, and portal data in order. Uses a fictional
sender. Never calls SendWhatsAppMessage.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

AWS_REGION = "us-east-1"
NAME_PREFIX = "cdshack-urbanbot-dev"
INBOUND_TOPIC = NAME_PREFIX + "-inbound"
INGEST_LOG_GROUP = "/aws/lambda/" + NAME_PREFIX + "-ingest"
CONSUMER_LOG_GROUP = "/aws/lambda/" + NAME_PREFIX + "-consumer"
AGENT_LOG_GROUP = "/aws/lambda/" + NAME_PREFIX + "-agent"
AUDIT_TABLE = NAME_PREFIX + "-audit-log"
REPORTS_TABLE = NAME_PREFIX + "-reports"
INCIDENTS_TABLE = NAME_PREFIX + "-incidents"
PORTAL_URL = "https://main.d1taemvhj3go47.amplifyapp.com/incidents"

FAKE_SENDER = "5215599900001"
FAKE_SENDER_MASK = "****0001"
META_PHONE_ID = "PNID"
AWS_PHONE_ID = "976c72a700aac43eaf573ae050example"
TEXT_BODY = "hola, humo de prueba urbanbot"
DEADLINE_S = 300
POLL_S = 3
STEPS = ("ingesta", "consumidor", "agente", "portal")
EVENT_ENQUEUED = "enqueued"
EVENT_AGENT_INVOKED = "agent_invoked"
EVENT_WOULD_SEND_REPLY = "WOULD_SEND_REPLY"


def build_eum_envelope(message_id, sender=FAKE_SENDER, text=TEXT_BODY):
    """SNS Message body matching modules/compute/tests/test_ingest_handler.py."""
    entry = {
        "id": "WABA",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                    "display_phone_number": "13192716611",
                    "phone_number_id": META_PHONE_ID,
                },
                "contacts": [{"profile": {"name": "Humo"}, "wa_id": sender}],
                "messages": [{
                    "from": sender,
                    "id": message_id,
                    "timestamp": str(int(time.time())),
                    "type": "text",
                    "text": {"body": text},
                }],
            },
        }],
    }
    return {
        "context": {
            "MetaWabaIds": [{
                "wabaId": "WABA",
                "arn": "arn:aws:social-messaging:us-east-1:000000000000:waba/x",
            }],
            "MetaPhoneNumberIds": [{
                "metaPhoneNumberId": META_PHONE_ID,
                "arn": (
                    "arn:aws:social-messaging:us-east-1:000000000000:"
                    "phone-number-id/" + AWS_PHONE_ID
                ),
            }],
        },
        "whatsAppWebhookEntry": json.dumps(entry),
        "aws_account_id": "636487155766",
        "message_timestamp": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "messageId": "sns-" + message_id,
    }


def new_message_id():
    return "wamid.SMOKE-" + uuid.uuid4().hex


def sns_lambda_event(envelope, sns_message_id="sns-local"):
    return {
        "Records": [{
            "EventSource": "aws:sns",
            "Sns": {
                "MessageId": sns_message_id,
                "Message": json.dumps(envelope),
            },
        }],
    }


def _ingest_handler_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(
        here, "..", "modules", "compute", "src", "ingest", "handler.py",
    ))


def load_ingest_handler():
    os.environ.setdefault("INGEST_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/000000000000/q.fifo")
    os.environ.setdefault("USERS_TABLE", "users")
    os.environ.setdefault("AUDIT_TABLE", "audit")
    os.environ.setdefault("AWS_DEFAULT_REGION", AWS_REGION)
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    path = _ingest_handler_path()
    spec = importlib.util.spec_from_file_location("urbanbot_ingest_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeSqs:
    def __init__(self):
        self.bodies = []

    def send_message(self, **kwargs):
        self.bodies.append(kwargs.get("MessageBody") or "")
        return {}

    def send_message_batch(self, **kwargs):
        for entry in kwargs.get("Entries") or []:
            self.bodies.append(entry.get("MessageBody") or "")
        return {}


class _FakeDdb:
    def put_item(self, **kwargs):
        return {}

    def get_item(self, **kwargs):
        return {}

    def update_item(self, **kwargs):
        return {"Attributes": {}}


def queued_payloads(sqs):
    out = []
    for raw in sqs.bodies:
        try:
            out.append(json.loads(raw) if raw else {})
        except (ValueError, TypeError):
            out.append({})
    return out


def run_local(hasta, message_id, sender=FAKE_SENDER, text=TEXT_BODY, handler=None):
    """Drive the repo ingest handler in-process. Does not call AWS."""
    if handler is None:
        handler = load_ingest_handler()
    sqs = _FakeSqs()
    handler._sqs = sqs
    handler._ddb = _FakeDdb()
    handler._already_processed = lambda *a, **k: False
    handler._check_consent = lambda *a, **k: True
    handler._check_rate_limit = lambda *a, **k: False
    envelope = build_eum_envelope(message_id, sender=sender, text=text)
    handler.lambda_handler(sns_lambda_event(envelope, "sns-" + message_id), None)
    payloads = queued_payloads(sqs)
    if len(payloads) != 1:
        _print_step(
            "ingesta",
            False,
            "local encoló %s mensajes, se esperaba 1" % len(payloads),
        )
        return 1
    body = payloads[0]
    got_user = body.get("user_id")
    got_text = body.get("text")
    ok = got_user == sender and got_text == text
    if ok:
        detail = "local EUM user_id y text encolados message_id=%s" % message_id
    else:
        text_len = len(got_text) if isinstance(got_text, str) else 0
        detail = "encolado user_id=%r text_len=%s, esperado remitente ficticio y text" % (
            got_user, text_len,
        )
    _print_step("ingesta", ok, detail)
    if not ok:
        return 1
    if step_rank(hasta) > 0:
        _print_step(
            hasta,
            False,
            "--local solo cubre ingesta; use el job smoke:whatsapp contra dev",
        )
        return 1
    return 0


def parse_hasta(value):
    if value not in STEPS:
        raise argparse.ArgumentTypeError(
            "debe ser uno de: " + ", ".join(STEPS)
        )
    return value


def step_rank(hasta):
    return STEPS.index(hasta)


def log_matches_event(message, event_name, message_id):
    if not message or not event_name or not message_id:
        return False
    if message_id not in message:
        return False
    needle = '"event": "' + event_name + '"'
    alt = '"event":"' + event_name + '"'
    return needle in message or alt in message or event_name in message


def _print_step(name, ok, detail):
    mark = "pasa" if ok else "falla"
    print("%s: %s (%s)" % (name, mark, detail), flush=True)


def _aws_error_detail(exc):
    response = getattr(exc, "response", None) or {}
    err = response.get("Error") if isinstance(response, dict) else None
    if isinstance(err, dict):
        code = err.get("Code") or "ClientError"
        action = err.get("Message") or str(exc)
        return "permiso AWS %s: %s" % (code, action)
    return str(exc)


class Smoke:
    def __init__(self, sns, logs, ddb, sleep=time.sleep, monotonic=time.monotonic):
        self.sns = sns
        self.logs = logs
        self.ddb = ddb
        self.sleep = sleep
        self.monotonic = monotonic

    def wait_for_log(self, log_group, event_name, message_id, start_ms, deadline):
        while self.monotonic() < deadline:
            try:
                resp = self.logs.filter_log_events(
                    logGroupName=log_group,
                    startTime=start_ms,
                    filterPattern='"%s"' % message_id,
                    limit=50,
                )
            except Exception as exc:  # boto ClientError/BotoCoreError
                raise RuntimeError(_aws_error_detail(exc)) from exc
            for event in resp.get("events") or []:
                msg = event.get("message") or ""
                if log_matches_event(msg, event_name, message_id):
                    return msg
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                break
            self.sleep(min(POLL_S, remaining))
        return None

    def query_audit(self, entity_id):
        try:
            resp = self.ddb.query(
                TableName=AUDIT_TABLE,
                KeyConditionExpression="entity_id = :e",
                ExpressionAttributeValues={":e": {"S": entity_id}},
                Limit=1,
            )
        except Exception as exc:
            raise RuntimeError(_aws_error_detail(exc)) from exc
        return bool(resp.get("Items"))

    def reports_for_sender(self, sender):
        try:
            resp = self.ddb.query(
                TableName=REPORTS_TABLE,
                IndexName="by-user",
                KeyConditionExpression="user_id = :u",
                ExpressionAttributeValues={":u": {"S": sender}},
                ScanIndexForward=False,
                Limit=5,
            )
        except Exception as exc:
            raise RuntimeError(_aws_error_detail(exc)) from exc
        return resp.get("Items") or []

    def get_incident(self, incident_id):
        try:
            resp = self.ddb.get_item(
                TableName=INCIDENTS_TABLE,
                Key={"incident_id": {"S": incident_id}},
            )
        except Exception as exc:
            raise RuntimeError(_aws_error_detail(exc)) from exc
        return resp.get("Item")

    def publish(self, envelope):
        try:
            return self.sns.publish(
                TopicArn=(
                    "arn:aws:sns:%s:636487155766:%s" % (AWS_REGION, INBOUND_TOPIC)
                ),
                Message=json.dumps(envelope),
            )
        except Exception as exc:
            raise RuntimeError(_aws_error_detail(exc)) from exc

    def run(self, hasta, message_id, sender=FAKE_SENDER, deadline=None):
        if deadline is None:
            deadline = self.monotonic() + DEADLINE_S
        rank = step_rank(hasta)
        start_ms = int(time.time() * 1000) - 5000
        envelope = build_eum_envelope(message_id, sender=sender)
        published = self.publish(envelope)
        sns_id = published.get("MessageId") or ""

        ingest_msg = self.wait_for_log(
            INGEST_LOG_GROUP, EVENT_ENQUEUED, message_id, start_ms, deadline,
        )
        ok = bool(ingest_msg)
        _print_step(
            "ingesta",
            ok,
            "enqueued %s sns=%s" % (message_id, sns_id) if ok
            else "no apareció log enqueued con %s" % message_id,
        )
        if not ok:
            return 1
        if rank == 0:
            return 0

        consumer_msg = self.wait_for_log(
            CONSUMER_LOG_GROUP, EVENT_AGENT_INVOKED, message_id, start_ms, deadline,
        )
        ok = bool(consumer_msg)
        _print_step(
            "consumidor",
            ok,
            "agent_invoked %s" % message_id if ok
            else "no apareció agent_invoked con %s" % message_id,
        )
        if not ok:
            return 1
        if rank == 1:
            return 0

        try:
            in_audit = (
                self.query_audit("msgid#" + message_id)
                or self.query_audit("inbound#" + message_id)
            )
        except RuntimeError as exc:
            _print_step("agente", False, str(exc))
            return 1
        reply_msg = self.wait_for_log(
            AGENT_LOG_GROUP, EVENT_WOULD_SEND_REPLY, message_id,
            start_ms, deadline,
        )
        if not in_audit:
            _print_step(
                "agente",
                False,
                "sin registro DynamoDB msgid#/inbound# %s" % message_id,
            )
            return 1
        if not reply_msg:
            _print_step(
                "agente",
                False,
                "sin WOULD_SEND_REPLY (el zip desplegado puede no tener el "
                "simulador; hace falta aplicar el modelo nuevo)",
            )
            return 1
        if FAKE_SENDER in (reply_msg or ""):
            _print_step("agente", False, "WOULD_SEND_REPLY expuso el destino")
            return 1
        _print_step(
            "agente",
            True,
            "DynamoDB + WOULD_SEND_REPLY destino=%s" % FAKE_SENDER_MASK,
        )
        if rank == 2:
            return 0

        try:
            reports = self.reports_for_sender(sender)
        except RuntimeError as exc:
            _print_step("portal", False, str(exc))
            return 1
        incident_ids = []
        for item in reports:
            iid = (item.get("incident_id") or {}).get("S")
            if iid:
                incident_ids.append(iid)
        if not incident_ids:
            _print_step(
                "portal",
                True,
                "el agente no creó incidente; portal no aplica (%s)" % PORTAL_URL,
            )
            return 0
        found = []
        for iid in incident_ids:
            item = self.get_incident(iid)
            if item:
                found.append(iid)
        if not found:
            _print_step(
                "portal",
                False,
                "reportes con incident_id %s ausentes en %s" % (
                    ",".join(incident_ids), INCIDENTS_TABLE,
                ),
            )
            return 1
        _print_step(
            "portal",
            True,
            "incidente %s en %s (origen de %s)" % (
                found[0], INCIDENTS_TABLE, PORTAL_URL,
            ),
        )
        return 0


def build_clients():
    import boto3
    session = boto3.Session(region_name=AWS_REGION)
    return (
        session.client("sns"),
        session.client("logs"),
        session.client("dynamodb"),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Humo WhatsApp (SNS ficticio, sin envío real).",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Pasar el envelope EUM por la ingesta del repo, sin AWS.",
    )
    parser.add_argument(
        "--hasta",
        type=parse_hasta,
        default=None,
        help="Cortar la verificación en este paso: " + ", ".join(STEPS),
    )
    args = parser.parse_args(argv)
    hasta = args.hasta or ("ingesta" if args.local else "portal")
    if FAKE_SENDER == "":
        print("falla: el remitente ficticio no está configurado", flush=True)
        return 1
    message_id = new_message_id()
    if args.local:
        return run_local(hasta, message_id)
    deadline = time.monotonic() + DEADLINE_S
    try:
        sns, logs, ddb = build_clients()
        smoke = Smoke(sns, logs, ddb)
        return smoke.run(hasta, message_id, deadline=deadline)
    except RuntimeError as exc:
        print("falla: %s" % exc, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
