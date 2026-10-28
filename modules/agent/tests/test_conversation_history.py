"""Execute agent turns and privacy erasure against DynamoDB with moto."""
import importlib.util
import os
from pathlib import Path
import sys
import time
from unittest import mock

import boto3
from moto import mock_aws
import pytest

ROOT = Path(__file__).parents[1] / "src"


def load(name, directory):
    spec = importlib.util.spec_from_file_location(name, ROOT / directory / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def app(monkeypatch):
    for name, value in {
        "AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing", "CONVERSATION_HISTORY_TABLE": "history",
        "AGENTCORE_MEMORY_ID": "", "AGENTCORE_IDENTITY_SECRET_ARN": "identity",
    }.items():
        monkeypatch.setenv(name, value)
    strands = mock.MagicMock()
    strands.tool = lambda fn: fn
    exceptions = mock.MagicMock()
    exceptions.ModelThrottledException = type("Throttled", (Exception,), {})
    with mock.patch.dict(sys.modules, {
        "strands": strands, "strands.models.bedrock": mock.MagicMock(),
        "strands.types.exceptions": exceptions,
    }), mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(TableName="history", BillingMode="PAY_PER_REQUEST",
                         KeySchema=[{"AttributeName": "citizen_id", "KeyType": "HASH"},
                                    {"AttributeName": "ts", "KeyType": "RANGE"}],
                         AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"}
                                               for k in ("citizen_id", "ts")])
        boto3.client("secretsmanager").create_secret(Name="identity", SecretString="private-key")
        agent = load("history_agent", "agent")
        deletion = load("history_deletion", "delete_my_data")
        seen = []

        class Agent:
            def __init__(self, **kwargs):
                self.messages = kwargs.get("messages", [])

            def __call__(self, prompt):
                seen.append(self.messages + [{"role": "user", "content": [{"text": prompt}]}])
                return "Dime la ubicacion"

        agent.Agent = Agent
        agent.BedrockModel = mock.Mock()
        yield agent, deletion, ddb, seen


def invoke(agent, text="Hay un bache", user="5215512345678", **flags):
    return agent.lambda_handler({"user_id": user, "text": text, **flags}, None)


def rows(ddb):
    return ddb.scan(TableName="history")["Items"]


def test_second_turn_restores_first_and_isolates_citizens(app, caplog):
    agent, _, ddb, seen = app
    assert invoke(agent)["ok"]
    assert invoke(agent, "Avenida Central")["ok"]
    assert seen[1] == [
        {"role": "user", "content": [{"text": "Hay un bache"}]},
        {"role": "assistant", "content": [{"text": "Dime la ubicacion"}]},
        {"role": "user", "content": [{"text": "Avenida Central"}]},
    ]
    assert invoke(agent, user="other")["ok"]
    assert len(seen[-1]) == 1
    item = rows(ddb)[0]
    assert item["citizen_id"]["S"] == agent._citizen_key("5215512345678")
    assert 604795 <= int(item["expires_at"]["N"]) - int(time.time()) <= 604800
    assert "Hay un bache" not in caplog.text
    assert "Avenida Central" not in caplog.text
    assert "5215512345678" not in caplog.text


def test_pending_consent_neither_loads_nor_saves(app):
    agent, _, ddb, seen = app
    invoke(agent)
    before = rows(ddb)
    assert invoke(agent, "privado", consent_pending=True)["ok"]
    assert rows(ddb) == before
    assert len(seen[-1]) == 1


@pytest.mark.parametrize("operation", ["query", "put_item"])
def test_dynamodb_failure_keeps_reply(app, operation):
    agent, _, _, _ = app
    with mock.patch.object(agent._ddb, operation, side_effect=RuntimeError("unavailable")):
        assert invoke(agent) == {"ok": True, "reply": "Dime la ubicacion"}


def test_unanswered_and_empty_turns_are_not_saved(app):
    agent, _, ddb, seen = app
    invoke(agent, "Hola")
    with mock.patch.object(agent, "Agent", side_effect=RuntimeError("timeout")):
        assert not invoke(agent, "fallido")["ok"]
    with mock.patch.object(agent, "_extract_reply", return_value=""):
        assert not invoke(agent, "vacio")["ok"]
    invoke(agent, "reintento")
    assert len(rows(ddb)) == 2
    assert len(seen[-1]) == 3
    assert seen[-1][0]["content"] == [{"text": "Hola"}]


@pytest.mark.parametrize("flags", [
    {"media": ["sanitized/photo.jpg"]},
    {"media_dropped": "rate_limited"},
    {"media_dropped": "processing_error"},
])
def test_captionless_media_turn_never_restores_blank_user_text(app, flags):
    agent, _, _, seen = app
    assert invoke(agent, "", **flags)["ok"]
    assert invoke(agent, "Avenida Central")["ok"]
    restored = seen[-1][:-1]
    assert [m["role"] for m in restored] == ["user", "assistant"]
    assert all(block["text"].strip() for m in restored for block in m["content"])
    assert restored[0]["content"][0]["text"] == seen[0][0]["content"][0]["text"]


def test_recent_ten_completed_turns_only(app):
    agent, _, ddb, seen = app
    key = agent._citizen_key("5215512345678")
    ddb.put_item(TableName="history", Item={
        "citizen_id": {"S": key}, "ts": {"S": "2000-01-01T00:00:00+00:00"},
        "expires_at": {"N": "1"}, "user": {"S": "expired"}, "assistant": {"S": "old"},
    })
    for i in range(12):
        invoke(agent, str(i))
    assert len(seen[-1]) == 21
    assert seen[-1][0]["content"] == [{"text": "1"}]


def test_two_turn_deletion_erases_history_without_recreating_it(app):
    agent, deletion, ddb, seen = app
    invoke(agent, "Quiero borrar mis datos")
    invoke(agent, "otro", user="other")
    deletion._delete_places = mock.Mock(return_value=0)
    deletion._anonymize_reports = mock.Mock(return_value=0)
    deletion._unsubscribe_incidents = mock.Mock()
    deletion._audit = mock.Mock()
    real_delete = deletion._ddb.delete_item
    deletion._ddb.delete_item = lambda **kw: real_delete(**kw) if kw["TableName"] == "history" else {}

    def delete_tool(fn, payload):
        assert payload == {"user_id": "5215512345678", "confirmed": True}
        return deletion.lambda_handler(payload, None)

    agent._invoke_tool = delete_tool

    class DeletingAgent:
        def __init__(self, **kwargs):
            assert kwargs["messages"][0]["content"] == [{"text": "Quiero borrar mis datos"}]

        def __call__(self, prompt):
            assert agent.delete_my_data()["ok"]
            return "Datos borrados"

    agent.Agent = DeletingAgent
    assert invoke(agent, "CONFIRMO BORRAR MIS DATOS")["ok"]
    remaining = rows(ddb)
    assert len(remaining) == 1
    assert remaining[0]["citizen_id"]["S"] == agent._citizen_key("other")
