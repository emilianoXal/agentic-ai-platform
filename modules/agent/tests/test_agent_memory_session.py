"""AgentCore Memory session continuity for the citizen agent."""

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-5-20250929-v1:0",
})

_strands = mock.MagicMock()
_exceptions = mock.MagicMock()


class _ModelThrottled(Exception):
    pass


_exceptions.ModelThrottledException = _ModelThrottled
sys.modules.setdefault("strands", _strands)
sys.modules.setdefault("strands.models.bedrock", mock.MagicMock())
sys.modules.setdefault("strands.types.exceptions", _exceptions)

_HANDLER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "agent", "handler.py",
)
_spec = importlib.util.spec_from_file_location(
    "urbanbot_agent_memory_handler", _HANDLER_PATH,
)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


class _Result:
    message = None

    def __init__(self, reply):
        self.reply = reply

    def __str__(self):
        return self.reply


class _MemoryClient:
    def __init__(self):
        self.events = {}
        self.calls = []

    def list_events(self, memory_id, actor_id, session_id):
        self.calls.append(("list", memory_id, actor_id, session_id))
        return list(self.events.get((memory_id, actor_id, session_id), []))

    def create_event(self, memory_id, actor_id, session_id, messages):
        self.calls.append(("create", memory_id, actor_id, session_id))
        self.events.setdefault((memory_id, actor_id, session_id), []).extend(messages)


class _MemoryConfig:
    def __init__(self, memory_id, actor_id, session_id):
        self.memory_id = memory_id
        self.actor_id = actor_id
        self.session_id = session_id


class _SessionManager:
    client = _MemoryClient()
    configurations = []

    def __init__(self, agentcore_memory_config, region_name):
        self.config = agentcore_memory_config
        self.region_name = region_name
        self.configurations.append(agentcore_memory_config)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Agent:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.instances.append(self)

    def __call__(self, prompt):
        manager = self.kwargs.get("session_manager")
        if manager is None:
            return _Result("sin memoria")
        config = manager.config
        history = manager.client.list_events(
            config.memory_id, config.actor_id, config.session_id,
        )
        reply = "historial: " + " | ".join(history + [prompt])
        manager.client.create_event(
            config.memory_id,
            config.actor_id,
            config.session_id,
            [prompt, reply],
        )
        return _Result(reply)


def _agentcore_modules():
    config_module = types.ModuleType(
        "bedrock_agentcore.memory.integrations.strands.config",
    )
    config_module.AgentCoreMemoryConfig = _MemoryConfig
    manager_module = types.ModuleType(
        "bedrock_agentcore.memory.integrations.strands.session_manager",
    )
    manager_module.AgentCoreMemorySessionManager = _SessionManager
    return {
        "bedrock_agentcore": types.ModuleType("bedrock_agentcore"),
        "bedrock_agentcore.memory": types.ModuleType("bedrock_agentcore.memory"),
        "bedrock_agentcore.memory.integrations": types.ModuleType(
            "bedrock_agentcore.memory.integrations",
        ),
        "bedrock_agentcore.memory.integrations.strands": types.ModuleType(
            "bedrock_agentcore.memory.integrations.strands",
        ),
        config_module.__name__: config_module,
        manager_module.__name__: manager_module,
    }


class AgentMemorySessionTests(unittest.TestCase):
    def setUp(self):
        _SessionManager.client = _MemoryClient()
        _SessionManager.configurations = []
        _Agent.instances = []
        handler.Agent = _Agent
        handler.BedrockModel = mock.MagicMock()
        handler._lambda = mock.MagicMock()

    def _event(self, citizen, text):
        return {"user_id": citizen, "text": text, "type": "text"}

    def _invoke_with_memory(self, citizen, text):
        with mock.patch.dict(sys.modules, _agentcore_modules()), mock.patch.object(
            handler, "AGENTCORE_MEMORY_ID", "memory-1234567890",
        ):
            return handler.lambda_handler(self._event(citizen, text), None)

    def test_same_citizen_restores_previous_turn(self):
        citizen = "5215512345678"
        first = self._invoke_with_memory(citizen, "Hay un bache")
        second = self._invoke_with_memory(citizen, "Esta en Avenida Central")

        self.assertTrue(first["ok"])
        self.assertIn("Hay un bache", second["reply"])
        first_config, second_config = _SessionManager.configurations
        self.assertEqual(first_config.actor_id, second_config.actor_id)
        self.assertEqual(first_config.session_id, second_config.session_id)
        self.assertNotIn(citizen, first_config.actor_id)
        self.assertNotIn(citizen, first_config.session_id)

    def test_different_citizens_have_isolated_sessions(self):
        self._invoke_with_memory("5215512345678", "Hay un bache")
        other = self._invoke_with_memory("5215587654321", "Donde esta el bache")

        self.assertNotIn("Hay un bache", other["reply"])
        first_config, second_config = _SessionManager.configurations
        self.assertNotEqual(first_config.actor_id, second_config.actor_id)
        self.assertNotEqual(first_config.session_id, second_config.session_id)

    def test_without_memory_does_not_call_memory_client(self):
        with mock.patch.object(handler, "AGENTCORE_MEMORY_ID", ""):
            result = handler.lambda_handler(
                self._event("5215512345678", "Hola"), None,
            )

        self.assertEqual(result, {"ok": True, "reply": "sin memoria"})
        self.assertEqual(_SessionManager.configurations, [])
        self.assertEqual(_SessionManager.client.calls, [])
        self.assertNotIn("session_manager", _Agent.instances[0].kwargs)


if __name__ == "__main__":
    unittest.main()
