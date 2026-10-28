"""Behavioral tests for the WhatsApp smoke runner.

Run: python3 -m unittest tests.test_smoke_whatsapp
"""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

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
    def __init__(self, reports=None, incidents=None, fail=None):
        self.reports = reports or []
        self.incidents = incidents or {}
        self.fail = fail
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.fail:
            raise self.fail
        table = kwargs.get("TableName")
        if table == smoke.REPORTS_TABLE:
            values = kwargs.get("ExpressionAttributeValues") or {}
            user = (values.get(":u") or {}).get("S")
            since = (values.get(":t") or {}).get("S")
            if not since:
                raise AssertionError("reports query must bound created_at")
            return {"Items": [
                r for r in self.reports
                if r["user_id"]["S"] == user and r["created_at"]["S"] >= since
            ]}
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
        "text_len": 14,
        "text_hash": "0123456789abcdef",
    })


def _report(incident_id, created_at):
    return {
        "user_id": {"S": smoke.FAKE_SENDER},
        "created_at": {"S": created_at},
        "incident_id": {"S": incident_id},
    }


_FUTURE = "2999-01-01T00:00:00+00:00"
_PAST = "2000-01-01T00:00:00+00:00"


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


class LocalIngestTests(unittest.TestCase):
    def test_local_ingesta_enqueues_fictional_sender_and_text(self):
        mid = "wamid.SMOKE-local1"
        code = smoke.run_local("ingesta", mid)
        self.assertEqual(code, 0)

    def test_local_cli_hasta_ingesta(self):
        code = smoke.main(["--local", "--hasta", "ingesta"])
        self.assertEqual(code, 0)

    def test_local_stops_before_later_steps(self):
        code = smoke.run_local("consumidor", "wamid.SMOKE-local2")
        self.assertEqual(code, 1)

    def test_local_does_not_build_aws_clients(self):
        with mock.patch.object(smoke, "build_clients") as build:
            code = smoke.main(["--local", "--hasta", "ingesta"])
        self.assertEqual(code, 0)
        build.assert_not_called()


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
            reports=[_report("inc-1", _FUTURE)],
            incidents={"inc-1": {"incident_id": {"S": "inc-1"}}},
        )
        runner = smoke.Smoke(
            _Sns(), logs, ddb, sleep=clock.sleep, monotonic=clock.monotonic,
        )
        code = runner.run("portal", mid, deadline=clock.now + 10)
        self.assertEqual(code, 0)

    def test_agent_step_needs_only_would_send_reply(self):
        clock = _Clock()
        mid = "wamid.SMOKE-agent"
        logs = _Logs([_enqueued(mid), _invoked(mid), _reply(mid)])
        ddb = _Ddb()
        runner = smoke.Smoke(
            _Sns(), logs, ddb, sleep=clock.sleep, monotonic=clock.monotonic,
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = runner.run("agente", mid, deadline=clock.now + 10)
        self.assertEqual(code, 0)
        self.assertEqual(ddb.queries, [])
        self.assertIn("text_len=14", out.getvalue())

    def test_agent_step_fails_without_text_len(self):
        clock = _Clock()
        mid = "wamid.SMOKE-nolen"
        bare = json.dumps({"event": "WOULD_SEND_REPLY", "message_id": mid})
        logs = _Logs([_enqueued(mid), _invoked(mid), bare])
        runner = smoke.Smoke(
            _Sns(), logs, _Ddb(), sleep=clock.sleep, monotonic=clock.monotonic,
        )
        code = runner.run("agente", mid, deadline=clock.now + 10)
        self.assertEqual(code, 1)

    def test_portal_ignores_reports_from_prior_runs(self):
        clock = _Clock()
        mid = "wamid.SMOKE-old"
        logs = _Logs([_enqueued(mid), _invoked(mid), _reply(mid)])
        ddb = _Ddb(reports=[_report("inc-gone", _PAST)])
        runner = smoke.Smoke(
            _Sns(), logs, ddb, sleep=clock.sleep, monotonic=clock.monotonic,
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = runner.run("portal", mid, deadline=clock.now + 10)
        self.assertEqual(code, 0)
        self.assertIn("no creó incidente", out.getvalue())


if __name__ == "__main__":
    unittest.main()
