"""AgentCore Memory session continuity for the citizen agent."""

import hashlib
import importlib.util
import json
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


class _SessionMessage:
    """Mirrors strands SessionMessage: restored message_id is the persisted 0."""

    def __init__(self, message, message_id=0):
        self.message = message
        self.message_id = message_id

    def to_message(self):
        return dict(self.message)


class _Converter:
    """Mirrors AgentCoreMemoryConverter.events_to_messages (newest-first input)."""

    @staticmethod
    def events_to_messages(events):
        messages = []
        for event in reversed(events):
            for payload in event.get("payload", []):
                if "conversational" in payload:
                    data = json.loads(payload["conversational"]["content"]["text"])
                    messages.append(
                        _SessionMessage(data["message"], data["message_id"]),
                    )
        return messages


class _DataPlane:
    def __init__(self, store):
        self.store = store

    def delete_event(self, memoryId, actorId, sessionId, eventId):
        if not isinstance(eventId, str):
            raise TypeError("eventId must be a string")
        events = self.store.events[(memoryId, actorId, sessionId)]
        events[:] = [event for event in events if event["eventId"] != eventId]


class _MemoryClient:
    """Raw AgentCore events, chronological in storage, newest first on list."""

    def __init__(self):
        self.events = {}
        self.calls = []
        self.gmdp_client = _DataPlane(self)
        self._next_id = 0

    def list_events(self, memory_id, actor_id, session_id, max_results=100):
        key = (memory_id, actor_id, session_id)
        self.calls.append(("list",) + key)
        return list(reversed(self.events.get(key, [])))[:max_results]

    def _append(self, key, payload):
        self._next_id += 1
        self.events.setdefault(key, []).append(
            {"eventId": f"{self._next_id:013d}#evt", "payload": [payload]},
        )

    def create_message_event(self, key, message):
        self.calls.append(("create",) + key)
        text = json.dumps({"message": message, "message_id": 0})
        self._append(key, {"conversational": {
            "content": {"text": text}, "role": message["role"].upper(),
        }})

    def create_state_event(self, key):
        self.calls.append(("create",) + key)
        self._append(key, {"blob": json.dumps({"agent_id": "default"})})


class _PersistenceMode:
    FULL = "FULL"
    NONE = "NONE"


class _MemoryConfig:
    def __init__(self, memory_id, actor_id, session_id,
                 persistence_mode=_PersistenceMode.FULL):
        self.memory_id = memory_id
        self.actor_id = actor_id
        self.session_id = session_id
        self.persistence_mode = persistence_mode


class _SessionManager:
    """Persists each message as soon as it is added, like the real manager."""

    memory_client = _MemoryClient()
    configurations = []

    def __init__(self, agentcore_memory_config, region_name):
        self.config = agentcore_memory_config
        self.region_name = region_name
        self.converter = _Converter
        self.configurations.append(agentcore_memory_config)

    @property
    def _key(self):
        return (self.config.memory_id, self.config.actor_id, self.config.session_id)

    def list_messages(self, session_id, agent_id):
        assert session_id == self.config.session_id
        return self.converter.events_to_messages(
            self.memory_client.list_events(*self._key),
        )

    def append_message(self, message):
        if self.config.persistence_mode != _PersistenceMode.NONE:
            self.memory_client.create_message_event(self._key, message)

    def sync_agent(self):
        if self.config.persistence_mode != _PersistenceMode.NONE:
            self.memory_client.create_state_event(self._key)

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
            partial_messages, error = self.model_failures.pop(0)
            for message in partial_messages:
                self._add(message)
            raise error
        if self.kwargs.get("session_manager") is None:
            reply = "sin memoria"
        else:
            reply = "historial: " + " | ".join(
                block["text"] for m in self.messages if m["role"] == "user"
                for block in m["content"] if "text" in block
            )
        self._add(_text("assistant", reply))
        manager = self.kwargs.get("session_manager")
        if manager is not None:
            manager.sync_agent()
        return _Result(reply)


def _agentcore_modules():
    config_module = types.ModuleType(
        "bedrock_agentcore.memory.integrations.strands.config",
    )
    config_module.AgentCoreMemoryConfig = _MemoryConfig
    config_module.PersistenceMode = _PersistenceMode
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
        _SessionManager.memory_client = _MemoryClient()
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

    def _stored_roles(self):
        return [
            json.loads(payload["conversational"]["content"]["text"])["message"]["role"]
            for events in _SessionManager.memory_client.events.values()
            for event in events
            for payload in event["payload"]
            if "conversational" in payload
        ]

    def _last_model_roles(self):
        return [m["role"] for m in _Agent.instances[-1].model_inputs[-1]]

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

    def test_deletion_confirmation_turn_restores_history_but_persists_nothing(self):
        citizen = "5215512345678"
        self._invoke_with_memory(citizen, "Quiero borrar mis datos")
        events_before = list(_SessionManager.memory_client.events.values())[0][:]

        confirmed = self._invoke_with_memory(citizen, "CONFIRMO BORRAR MIS DATOS")

        self.assertTrue(confirmed["ok"])
        self.assertEqual(self._last_model_roles(), ["user", "assistant", "user"])
        self.assertEqual(
            list(_SessionManager.memory_client.events.values())[0], events_before,
        )

    def test_answered_history_is_kept_intact(self):
        citizen = "5215512345678"
        self._invoke_with_memory(citizen, "Hay un bache")
        second = self._invoke_with_memory(citizen, "Esta en Avenida Central")

        self.assertIn("Hay un bache", second["reply"])
        self.assertEqual(self._last_model_roles(), ["user", "assistant", "user"])
        self.assertEqual(self._stored_roles(),
                         ["user", "assistant", "user", "assistant"])

    def test_retried_failed_turn_does_not_leave_orphan_user_message(self):
        citizen = "5215512345678"
        self._invoke_with_memory(citizen, "Hola")
        _Agent.model_failures = [([], handler.ModelThrottledException())]
        failed = self._invoke_with_memory(citizen, "Hay un bache")
        retried = self._invoke_with_memory(citizen, "Hay un bache")

        self.assertEqual(failed, {"ok": False, "error": "bedrock_throttled"})
        self.assertTrue(retried["ok"])
        self.assertEqual(self._last_model_roles(), ["user", "assistant", "user"])
        self.assertEqual(self._stored_roles(),
                         ["user", "assistant", "user", "assistant"])

    def test_retried_turn_drops_orphan_tool_exchange(self):
        citizen = "5215512345678"
        self._invoke_with_memory(citizen, "Hola")
        tool_exchange = [
            {"role": "assistant", "content": [{"toolUse": {
                "toolUseId": "t1", "name": "create_report", "input": {},
            }}]},
            {"role": "user", "content": [{"toolResult": {
                "toolUseId": "t1", "content": [{"text": "ok"}],
            }}]},
        ]
        _Agent.model_failures = [(tool_exchange, RuntimeError("lambda timeout"))]
        failed = self._invoke_with_memory(citizen, "Hay un bache")
        retried = self._invoke_with_memory(citizen, "Hay un bache")

        self.assertEqual(failed, {"ok": False, "error": "internal"})
        self.assertTrue(retried["ok"])
        self.assertEqual(self._last_model_roles(), ["user", "assistant", "user"])
        self.assertEqual(self._stored_roles(),
                         ["user", "assistant", "user", "assistant"])

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
