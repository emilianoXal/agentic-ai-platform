"""Behavioral tests for the WhatsApp smoke runner.

Run: python3 -m unittest tests.test_smoke_whatsapp
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import smoke_whatsapp as smoke  # noqa: E402


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class _Logs:
    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = []

    def filter_log_events(self, **kwargs):
        self.calls.append(kwargs)
        needle = (kwargs.get("filterPattern") or "").strip('"')
        events = []
        for msg in self.messages:
            if needle and needle in msg:
                events.append({"message": msg})
        return {"events": events}


class _Sns:
    def __init__(self, fail=None):
        self.fail = fail
        self.published = []

    def publish(self, **kwargs):
        self.published.append(kwargs)
        if self.fail:
            raise self.fail
        return {"MessageId": "sns-smoke-1"}


class _Ddb:
    def __init__(self, audit=None, reports=None, incidents=None, fail=None):
        self.audit = audit or {}
        self.reports = reports or []
        self.incidents = incidents or {}
        self.fail = fail
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.fail:
            raise self.fail
        table = kwargs.get("TableName")
        if table == smoke.AUDIT_TABLE:
            values = kwargs.get("ExpressionAttributeValues") or {}
            entity = (values.get(":e") or {}).get("S")
            if entity in self.audit:
                return {"Items": [self.audit[entity]]}
            return {"Items": []}
        if table == smoke.REPORTS_TABLE:
            return {"Items": list(self.reports)}
        return {"Items": []}

    def get_item(self, **kwargs):
        if self.fail:
            raise self.fail
        key = ((kwargs.get("Key") or {}).get("incident_id") or {}).get("S")
        item = self.incidents.get(key)
        return {"Item": item} if item else {}


def _enqueued(mid):
    return json.dumps({"event": "enqueued", "message_id": mid})


def _invoked(mid):
    return json.dumps({"event": "agent_invoked", "message_id": mid})


def _reply(mid):
    return json.dumps({
        "event": "WOULD_SEND_REPLY",
        "message_id": mid,
        "recipient": "****0001",
        "text": "hola de vuelta",
    })


class EnvelopeTests(unittest.TestCase):
    def test_eum_envelope_uses_fictional_sender_and_unique_wamid(self):
        mid = "wamid.SMOKE-abc"
        env = smoke.build_eum_envelope(mid)
        self.assertEqual(env["messageId"], "sns-" + mid)
        entry = json.loads(env["whatsAppWebhookEntry"])
        msg = entry["changes"][0]["value"]["messages"][0]
        self.assertEqual(msg["from"], smoke.FAKE_SENDER)
        self.assertEqual(msg["id"], mid)
        self.assertEqual(msg["text"]["body"], smoke.TEXT_BODY)
        self.assertTrue(smoke.FAKE_SENDER.startswith("52155999"))
        self.assertIn("whatsAppWebhookEntry", env)
        self.assertIn("MetaPhoneNumberIds", env["context"])

    def test_log_matches_requires_event_and_id(self):
        mid = "wamid.SMOKE-x"
        line = _enqueued(mid)
        self.assertTrue(smoke.log_matches_event(line, "enqueued", mid))
        self.assertFalse(smoke.log_matches_event(line, "enqueued", "other"))
        self.assertFalse(smoke.log_matches_event(line, "agent_invoked", mid))


class FailFastTests(unittest.TestCase):
    def test_ingest_failure_does_not_wait_on_consumer(self):
        clock = _Clock()
        logs = _Logs([])
        sns = _Sns()
        ddb = _Ddb()
        runner = smoke.Smoke(
            sns, logs, ddb, sleep=clock.sleep, monotonic=clock.monotonic,
        )
        code = runner.run("portal", "wamid.SMOKE-miss", deadline=clock.now + 1)
        self.assertEqual(code, 1)
        self.assertEqual(len(sns.published), 1)
        groups = [c["logGroupName"] for c in logs.calls]
        self.assertEqual(set(groups), {smoke.INGEST_LOG_GROUP})
        self.assertEqual(ddb.queries, [])

    def test_hasta_ingesta_stops_after_enqueued(self):
        clock = _Clock()
        mid = "wamid.SMOKE-ok"
        logs = _Logs([_enqueued(mid), _invoked(mid)])
        sns = _Sns()
        ddb = _Ddb()
        runner = smoke.Smoke(
            sns, logs, ddb, sleep=clock.sleep, monotonic=clock.monotonic,
        )
        code = runner.run("ingesta", mid, deadline=clock.now + 10)
        self.assertEqual(code, 0)
        groups = [c["logGroupName"] for c in logs.calls]
        self.assertEqual(set(groups), {smoke.INGEST_LOG_GROUP})
        body = json.loads(sns.published[0]["Message"])
        self.assertEqual(
            json.loads(body["whatsAppWebhookEntry"])["changes"][0]["value"]
            ["messages"][0]["from"],
            smoke.FAKE_SENDER,
        )

    def test_full_path_portal_when_incident_exists(self):
        clock = _Clock()
        mid = "wamid.SMOKE-full"
        logs = _Logs([_enqueued(mid), _invoked(mid), _reply(mid)])
        ddb = _Ddb(
            audit={"inbound#" + mid: {"entity_id": {"S": "inbound#" + mid}}},
            reports=[{"incident_id": {"S": "inc-1"}}],
            incidents={"inc-1": {"incident_id": {"S": "inc-1"}}},
        )
        runner = smoke.Smoke(
            _Sns(), logs, ddb, sleep=clock.sleep, monotonic=clock.monotonic,
        )
        code = runner.run("portal", mid, deadline=clock.now + 10)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
