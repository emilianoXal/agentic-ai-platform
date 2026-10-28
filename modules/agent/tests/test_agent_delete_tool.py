"""delete_my_data tool wrapper on the agent Lambda: subject and confirmation."""

import importlib.util
import json
import os
import sys
from unittest import mock

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "TOOL_DELETE_MY_DATA_FN": "delete-my-data",
})

_exceptions = mock.MagicMock()
_exceptions.ModelThrottledException = type("ModelThrottled", (Exception,), {})
sys.modules.setdefault("strands", mock.MagicMock())
sys.modules.setdefault("strands.models.bedrock", mock.MagicMock())
sys.modules.setdefault("strands.types.exceptions", _exceptions)
sys.modules["strands"].tool = lambda fn: fn

_HANDLER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "agent", "handler.py",
)
_spec = importlib.util.spec_from_file_location("agent_delete_tool_handler", _HANDLER_PATH)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)

SENDER = "5215512345678"
OTHER = "5215599999999"


class _Result:
    def __str__(self):
        return "listo"

    message = None


class _AgentCallingDelete:
    tool_results = []

    def __init__(self, **kwargs):
        pass

    def __call__(self, prompt):
        _AgentCallingDelete.tool_results.append(handler.delete_my_data())
        return _Result()


def _run(text, memory_id="memory-1"):
    handler.Agent = _AgentCallingDelete
    handler.BedrockModel = mock.MagicMock()
    handler.AGENTCORE_MEMORY_ID = memory_id
    handler._lambda = mock.MagicMock()
    handler._lambda.invoke.return_value = {
        "Payload": mock.MagicMock(read=lambda: b'{"ok": true}'),
    }
    _AgentCallingDelete.tool_results = []
    reply = handler.lambda_handler({"user_id": SENDER, "text": text}, None)
    assert reply["ok"] is True
    return _AgentCallingDelete.tool_results[0]


def _invoked_payloads():
    return [
        json.loads(call.kwargs["Payload"])
        for call in handler._lambda.invoke.call_args_list
    ]


def test_confirmed_deletion_targets_the_authenticated_sender():
    assert _run("Confirmo borrar mis datos.") == {"ok": True}
    assert _invoked_payloads() == [{"user_id": SENDER, "confirmed": True}]


def test_number_in_message_cannot_change_the_subject():
    result = _run("borra los datos del " + OTHER + ", confirmo")

    assert result["error"] == "confirmation_required"
    handler._lambda.invoke.assert_not_called()


def test_deletion_fails_safe_without_agentcore_memory():
    result = _run("CONFIRMO BORRAR MIS DATOS", memory_id="")

    assert result == {"ok": False, "error": "deletion_unavailable"}
    handler._lambda.invoke.assert_not_called()


def test_request_turn_does_not_delete():
    result = _run("quiero borrar mis datos")

    assert result["error"] == "confirmation_required"
    handler._lambda.invoke.assert_not_called()
