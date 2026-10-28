"""AgentCore Memory session continuity for the citizen agent."""

import hashlib
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


class _StoredMessage:
    def __init__(self, event_id, message):
        self.message_id = event_id
        self.message = message

    def to_message(self):
        return dict(self.message)


class _DataPlane:
    def __init__(self, store):
        self.store = store

    def delete_event(self, memoryId, actorId, sessionId, eventId):
        events = self.store.events[(memoryId, actorId, sessionId)]
        events[:] = [event for event in events if event.message_id != eventId]


class _MemoryStore:
    def __init__(self):
        self.events = {}
        self.calls = []
        self.gmdp_client = _DataPlane(self)
        self._next_id = 0

    def list_events(self, key):
        self.calls.append(("list",) + key)
        return list(self.events.get(key, []))

    def create_event(self, key, message):
        self.calls.append(("create",) + key)
        self._next_id += 1
        self.events.setdefault(key, []).append(
            _StoredMessage(f"event-{self._next_id}", message),
        )


class _MemoryConfig:
    def __init__(self, memory_id, actor_id, session_id):
        self.memory_id = memory_id
        self.actor_id = actor_id
        self.session_id = session_id


class _SessionManager:
    """Persists each message as soon as it is added, like the real manager."""

    memory_client = _MemoryStore()
    configurations = []

    def __init__(self, agentcore_memory_config, region_name):
        self.config = agentcore_memory_config
        self.region_name = region_name
        self.configurations.append(agentcore_memory_config)

    @property
    def _key(self):
        return (self.config.memory_id, self.config.actor_id, self.config.session_id)

    def list_messages(self, session_id, agent_id):
        assert session_id == self.config.session_id
        return self.memory_client.list_events(self._key)

    def append_message(self, message):
        self.memory_client.create_event(self._key, message)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def _text(role, text):
    return {"role": role, "content": [{"text": text}]}


class _Agent:
    instances = []
    model_failures = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.instances.append(self)
        manager = kwargs.get("session_manager")
        self.messages = (
            [stored.to_message() for stored in
             manager.list_messages(manager.config.session_id, "default")]
            if manager else []
        )
        self.model_inputs = []

    def _add(self, message):
        self.messages.append(message)
        manager = self.kwargs.get("session_manager")
        if manager is not None:
            manager.append_message(message)

    def __call__(self, prompt):
        self._add(_text("user", prompt))
        self.model_inputs.append([dict(m) for m in self.messages])
        if self.model_failures:
            raise self.model_failures.pop(0)
        if self.kwargs.get("session_manager") is None:
            reply = "sin memoria"
        else:
            reply = "historial: " + " | ".join(
                m["content"][0]["text"] for m in self.messages if m["role"] == "user"
            )
        self._add(_text("assistant", reply))
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
        _SessionManager.memory_client = _MemoryStore()
        _SessionManager.configurations = []
        _Agent.instances = []
        _Agent.model_failures = []
        handler.Agent = _Agent
        handler.BedrockModel = mock.MagicMock()
        handler._lambda = mock.MagicMock()
        handler._identity_key = None
        handler._secrets = mock.MagicMock()
        handler._secrets.get_secret_value.return_value = {
            "SecretString": "identity-key-one",
        }

    def _event(self, citizen, text, consent_pending=False):
        return {"user_id": citizen, "text": text, "type": "text",
                "consent_pending": consent_pending}

    def _invoke_with_memory(self, citizen, text, consent_pending=False):
        with mock.patch.dict(sys.modules, _agentcore_modules()), mock.patch.multiple(
            handler,
            AGENTCORE_MEMORY_ID="memory-1234567890",
            AGENTCORE_IDENTITY_SECRET_ARN="arn:aws:secretsmanager:us-east-1:1:secret:id",
        ):
            return handler.lambda_handler(
                self._event(citizen, text, consent_pending), None,
            )

    def _stored_events(self):
        return [event for events in _SessionManager.memory_client.events.values()
                for event in events]

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

    def test_identity_is_keyed_hmac_not_plain_hash(self):
        citizen = "5215512345678"
        self._invoke_with_memory(citizen, "Hola")
        unsalted = hashlib.sha256(citizen.encode("utf-8")).hexdigest()
        first_config = _SessionManager.configurations[0]
        self.assertNotIn(unsalted, first_config.actor_id)
        self.assertNotIn(unsalted, first_config.session_id)
        handler._secrets.get_secret_value.assert_called_once_with(
            SecretId="arn:aws:secretsmanager:us-east-1:1:secret:id",
        )

        handler._identity_key = None
        handler._secrets.get_secret_value.return_value = {
            "SecretString": "identity-key-two",
        }
        self._invoke_with_memory(citizen, "Hola")
        second_config = _SessionManager.configurations[1]
        self.assertNotEqual(first_config.actor_id, second_config.actor_id)
        self.assertNotEqual(first_config.session_id, second_config.session_id)

    def test_different_citizens_have_isolated_sessions(self):
        self._invoke_with_memory("5215512345678", "Hay un bache")
        other = self._invoke_with_memory("5215587654321", "Donde esta el bache")

        self.assertNotIn("Hay un bache", other["reply"])
        first_config, second_config = _SessionManager.configurations
        self.assertNotEqual(first_config.actor_id, second_config.actor_id)
        self.assertNotEqual(first_config.session_id, second_config.session_id)

    def test_consent_pending_turn_persists_nothing(self):
        citizen = "5215512345678"
        pending = self._invoke_with_memory(citizen, "Hay un bache", consent_pending=True)

        self.assertTrue(pending["ok"])
        self.assertEqual(_SessionManager.configurations, [])
        self.assertEqual(_SessionManager.memory_client.calls, [])
        self.assertNotIn("session_manager", _Agent.instances[0].kwargs)
        handler._secrets.get_secret_value.assert_not_called()

        later = self._invoke_with_memory(citizen, "Acepto")
        self.assertNotIn("Hay un bache", later["reply"])

    def test_retried_failed_turn_does_not_leave_orphan_user_message(self):
        citizen = "5215512345678"
        self._invoke_with_memory(citizen, "Hola")
        _Agent.model_failures = [handler.ModelThrottledException()]
        failed = self._invoke_with_memory(citizen, "Hay un bache")
        retried = self._invoke_with_memory(citizen, "Hay un bache")

        self.assertEqual(failed, {"ok": False, "error": "bedrock_throttled"})
        self.assertTrue(retried["ok"])
        roles = [m["role"] for m in _Agent.instances[-1].model_inputs[-1]]
        self.assertEqual(roles, ["user", "assistant", "user"])
        stored_roles = [event.message["role"] for event in self._stored_events()]
        self.assertEqual(stored_roles, ["user", "assistant", "user", "assistant"])

    def test_without_memory_does_not_call_memory_client(self):
        with mock.patch.object(handler, "AGENTCORE_MEMORY_ID", ""):
            result = handler.lambda_handler(
                self._event("5215512345678", "Hola"), None,
            )

        self.assertEqual(result, {"ok": True, "reply": "sin memoria"})
        self.assertEqual(_SessionManager.configurations, [])
        self.assertEqual(_SessionManager.memory_client.calls, [])
        self.assertNotIn("session_manager", _Agent.instances[0].kwargs)


if __name__ == "__main__":
    unittest.main()
