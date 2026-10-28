"""urbanbot Strands agent Lambda.

The citizen-reporting agent for Queretaro urban infrastructure over WhatsApp.
Runs a Strands agent loop against Amazon Bedrock through a cross-region
inference profile, with a Bedrock Guardrail applied declaratively on the model.
The model only plans and converses; every state change is executed by the six
tool Lambdas exposed here as @tool wrappers (RNF-07). The consumer Lambda invokes
this function synchronously (RequestResponse) with the normalized inbound message.

Strands and its dependencies ship as a Lambda layer (modules/agent/layers/strands).
Only the stdlib + boto3 (bundled in the python3.12 Lambda runtime) are used outside
the layer. PII helpers are inlined verbatim (never imported across modules: the
agent zip contains only src/agent, so a cross-module import would fail at cold
start).

Verified against strands-agents==1.62.0:
  from strands import Agent, tool
  from strands.models.bedrock import BedrockModel  # model_id/guardrail_id/
                                                    # guardrail_version/region_name
  from strands.types.exceptions import ModelThrottledException
  result = agent(text); str(result) -> final reply text; result.message -> dict.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError

from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.types.exceptions import ModelThrottledException

# --- Config from environment -------------------------------------------------
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "")
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "")
TOOL_CREATE_REPORT_FN = os.environ.get("TOOL_CREATE_REPORT_FN", "")
TOOL_JOIN_INCIDENT_FN = os.environ.get("TOOL_JOIN_INCIDENT_FN", "")
TOOL_GET_STATUS_FN = os.environ.get("TOOL_GET_STATUS_FN", "")
TOOL_REGISTER_PLACE_FN = os.environ.get("TOOL_REGISTER_PLACE_FN", "")
TOOL_ROUTE_FN = os.environ.get("TOOL_ROUTE_FN", "")
TOOL_ESCALATE_FN = os.environ.get("TOOL_ESCALATE_FN", "")
AGENTCORE_MEMORY_ID = os.environ.get("AGENTCORE_MEMORY_ID", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
SIMULATE_WHATSAPP_REPLY = os.environ.get("SIMULATE_WHATSAPP_REPLY", "")
SMOKE_TEST_NUMBER = os.environ.get("SMOKE_TEST_NUMBER", "5215599900001")

AWS_REGION = "us-east-1"
# Target the cross-region inference profile, not the bare model id — matches
# local.inference_profile_arn and the IAM grant in modules/agent/main.tf.
INFERENCE_PROFILE_ID = "us." + BEDROCK_MODEL_ID if BEDROCK_MODEL_ID else ""

# --- Clients created at module load (reused across warm invocations) ---------
_lambda = boto3.client("lambda", region_name=AWS_REGION)

# --- Structured JSON-line logger (PII-masking; mirrors compute/ingest) -------
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


# --- PII helpers (inlined verbatim; never imported across modules) -----------
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


# --- Precision-7 geohash encoder (inlined; no new dependency) ----------------
_GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def _encode_geohash(lat, lng, precision=7):
    """Standard base-32 geohash encoder, interleaving lon/lat bits.

    Produces a precision-7 (35-bit -> 7-char) cell (~153 m). create_report and
    join_incident cluster on an EXACT-STRING equality Query of this geohash on
    the by-geohash GSI (RF-29), so the precision is fixed at 7 and must match
    the tool's assumption — any other precision silently breaks clustering.
    """
    lat = float(lat)
    lng = float(lng)
    lat_range = [-90.0, 90.0]
    lng_range = [-180.0, 180.0]
    geohash_chars = []
    bits = 0
    bit_count = 0
    even = True  # start with longitude
    while len(geohash_chars) < precision:
        if even:
            mid = (lng_range[0] + lng_range[1]) / 2
            if lng >= mid:
                bits = (bits << 1) | 1
                lng_range[0] = mid
            else:
                bits = bits << 1
                lng_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                bits = (bits << 1) | 1
                lat_range[0] = mid
            else:
                bits = bits << 1
                lat_range[1] = mid
        even = not even
        bit_count += 1
        if bit_count == 5:
            geohash_chars.append(_GEOHASH_BASE32[bits])
            bits = 0
            bit_count = 0
    return "".join(geohash_chars)


# --- Nested tool-Lambda invoke helper ----------------------------------------
def _invoke_tool(function_name, payload):
    """Synchronously invoke a tool Lambda and return its parsed JSON result.

    On any invoke failure (ClientError/BotoCoreError/FunctionError) return a
    structured {"ok": false, "error": "tool_invoke_failed"} to the model so it
    can recover and still produce a user-facing reply rather than crashing.
    """
    if not function_name:
        return {"ok": False, "error": "tool_invoke_failed"}
    try:
        resp = _lambda.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload, default=str).encode(),
        )
        if resp.get("FunctionError"):
            _log(logging.WARNING, "tool_function_error",
                 function_error=resp.get("FunctionError"))
            return {"ok": False, "error": "tool_invoke_failed"}
        raw = resp["Payload"].read()
        try:
            parsed = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            return {"ok": False, "error": "tool_invoke_failed"}
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "tool_invoke_failed"}
        return parsed
    except (ClientError, BotoCoreError):
        logger.exception(json.dumps({"event": "tool_invoke_exception"}))
        return {"ok": False, "error": "tool_invoke_failed"}


# --- Tool wrappers (one per tool Lambda; typed signatures + es-MX docstrings) -
@tool
def create_report(user_id: str, category: str, geohash: str, description: str,
                  media: list = None, lat: float = None, lng: float = None,
                  severity: str = None) -> dict:
    """Registra un nuevo reporte ciudadano de infraestructura urbana.

    Agrupa el reporte en un incidente abierto que comparta la misma celda
    geohash (precision 7) y categoria (RF-29). El geohash DEBE calcularse a
    partir de lat/lng con precision 7 antes de llamar a esta herramienta.

    Args:
        user_id: Identificador del usuario que reporta.
        category: Categoria del reporte (p.ej. bacheo, alumbrado, basura, agua).
        geohash: Celda geohash de precision 7 calculada desde lat/lng.
        description: Descripcion del reporte (obligatoria).
        media: Lista opcional de referencias a medios (claves S3 o URLs).
        lat: Latitud opcional (se guarda en el reporte).
        lng: Longitud opcional (se guarda en el reporte).
        severity: Severidad opcional (low, medium, high, critical).
    """
    return _invoke_tool(TOOL_CREATE_REPORT_FN, {
        "user_id": user_id,
        "category": category,
        "geohash": geohash,
        "description": description,
        "media": media,
        "lat": lat,
        "lng": lng,
        "severity": severity,
    })


@tool
def join_incident(incident_id: str, report_id: str = None, user_id: str = None,
                  category: str = None, geohash: str = None,
                  severity: str = None) -> dict:
    """Adjunta un reporte a un incidente abierto existente (RF-29/RF-10).

    Proporciona incident_id y exactamente uno de: report_id (adjunta un reporte
    existente) o user_id+category+geohash (crea un reporte y lo adjunta). El
    geohash debe ser de precision 7.

    Args:
        incident_id: Identificador del incidente abierto (obligatorio).
        report_id: Reporte existente a adjuntar.
        user_id: Usuario, para crear-y-adjuntar.
        category: Categoria, para crear-y-adjuntar.
        geohash: Celda geohash de precision 7, para crear-y-adjuntar.
        severity: Severidad opcional para recalcular prioridad.
    """
    return _invoke_tool(TOOL_JOIN_INCIDENT_FN, {
        "incident_id": incident_id,
        "report_id": report_id,
        "user_id": user_id,
        "category": category,
        "geohash": geohash,
        "severity": severity,
    })


@tool
def get_status(user_id: str = None, report_id: str = None) -> dict:
    """Consulta el estatus de un reporte o de todos los reportes de un usuario.

    Proporciona report_id o user_id (RF-16). Devuelve el estatus del reporte y
    del incidente padre.

    Args:
        user_id: Usuario del que listar reportes.
        report_id: Reporte especifico a consultar.
    """
    return _invoke_tool(TOOL_GET_STATUS_FN, {
        "user_id": user_id,
        "report_id": report_id,
    })


@tool
def register_place(user_id: str, alias: str, geohash: str = None,
                   lat: float = None, lng: float = None, place_id: str = None,
                   radius_m: int = None) -> dict:
    """Registra o actualiza un lugar de interes para el usuario (RF-23/RF-25).

    Maximo 3 lugares por usuario; requiere consentimiento previo. Proporciona
    geohash o lat/lng. Si lat/lng estan presentes, calcula el geohash de
    precision 7 antes de llamar.

    Args:
        user_id: Usuario dueno del lugar.
        alias: Nombre/etiqueta del lugar.
        geohash: Celda geohash de precision 7 (opcional si hay lat/lng).
        lat: Latitud opcional.
        lng: Longitud opcional.
        place_id: Id del lugar para actualizar uno existente.
        radius_m: Radio en metros del area de interes.
    """
    return _invoke_tool(TOOL_REGISTER_PLACE_FN, {
        "user_id": user_id,
        "alias": alias,
        "geohash": geohash,
        "lat": lat,
        "lng": lng,
        "place_id": place_id,
        "radius_m": radius_m,
    })


@tool
def route(category: str, incident_id: str = None, user_ids: list = None) -> dict:
    """Resuelve la dependencia responsable y canal de entrega de una categoria.

    Aplica las reglas de ruteo (RF-11/RF-12). Si se da incident_id, registra el
    ruteo en el incidente.

    Args:
        category: Categoria del reporte/incidente (obligatoria).
        incident_id: Incidente a marcar como ruteado (opcional).
        user_ids: Usuarios suscritos a notificar (opcional).
    """
    return _invoke_tool(TOOL_ROUTE_FN, {
        "category": category,
        "incident_id": incident_id,
        "user_ids": user_ids,
    })


@tool
def escalate(incident_id: str, reason: str = None, user_ids: list = None) -> dict:
    """Escala un incidente cuando cruza un umbral de reportes o antiguedad (RF-31).

    Args:
        incident_id: Incidente a evaluar/escalar (obligatorio).
        reason: Motivo opcional de la escalacion.
        user_ids: Usuarios suscritos a notificar (opcional).
    """
    return _invoke_tool(TOOL_ESCALATE_FN, {
        "incident_id": incident_id,
        "reason": reason,
        "user_ids": user_ids,
    })


_TOOLS = [create_report, join_incident, get_status, register_place, route, escalate]

# --- System prompt (concise es-MX) -------------------------------------------
_SYSTEM_PROMPT = (
    "Eres un asistente ciudadano de reportes de infraestructura urbana para "
    "Queretaro vIa WhatsApp. Ayudas a las personas a reportar baches, alumbrado, "
    "basura, fugas de agua y problemas similares, consultar el estatus de sus "
    "reportes y registrar lugares de interes. Tu solo propones y planeas: todos "
    "los cambios de estado los ejecutan las herramientas disponibles, nunca "
    "escribas directamente en los datos. Nunca repitas ni guardes numeros de "
    "telefono completos ni otra informacion personal; si consent_pending es "
    "verdadero, pide el consentimiento antes de actuar. Para crear o unir "
    "reportes necesitas la ubicacion (lat/lng); si falta, pidela y no inventes "
    "una celda. Responde corto, claro y en espanol de Mexico."
)


# --- es-MX canned replies ----------------------------------------------------
_ASK_FOR_TEXT = (
    "Hola, cuentame que problema de infraestructura urbana quieres reportar."
)
_TRY_AGAIN = (
    "Tuve un problema al procesar tu solicitud. Por favor intenta de nuevo en "
    "un momento."
)


def _extract_reply(result):
    """Extract the final assistant reply text from the Strands AgentResult.

    Verified shape (strands-agents==1.62.0): str(result) yields the final reply
    text; result.message is the structured role+content dict. Prefer str(result)
    and fall back to joining the text blocks of result.message.
    """
    text = ""
    try:
        text = str(result).strip()
    except Exception:  # noqa: BLE001 - never let extraction raise
        text = ""
    if text:
        return text
    message = getattr(result, "message", None)
    if isinstance(message, dict):
        parts = []
        for block in message.get("content", []) or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts).strip()
    return ""


def _simulate_outbound_enabled():
    value = os.environ.get("SIMULATE_WHATSAPP_REPLY", SIMULATE_WHATSAPP_REPLY)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _is_smoke_sender(user_id):
    smoke = re.sub(r"\D", "", os.environ.get("SMOKE_TEST_NUMBER", SMOKE_TEST_NUMBER))
    return bool(smoke) and re.sub(r"\D", "", str(user_id or "")) == smoke


def _record_simulated_reply(user_id, reply, message_id=None):
    """Log a verifiable outbound stand-in for the smoke sender only.

    Does not send WhatsApp and never logs the reply text.
    """
    if not _simulate_outbound_enabled() or not _is_smoke_sender(user_id):
        return
    text = reply if isinstance(reply, str) else ""
    _log(
        logging.INFO,
        "WOULD_SEND_REPLY",
        recipient=_mask_phone(user_id),
        text_len=len(text),
        text_hash=_hash_id(text),
        message_id=message_id,
    )


def lambda_handler(event, context):
    """Run the Strands agent on one inbound message and return {ok, reply, error?}.

    Never raises for ordinary failures: the consumer reads ok/error. Closed error
    set: invalid_input (terminal), bedrock_throttled (retriable), internal
    (retriable), tool_invoke_failed (terminal).
    """
    event = event if isinstance(event, dict) else {}
    user_id = event.get("user_id")
    text = event.get("text")

    # Defensive validation (invalid_input is terminal; consumer does not redrive).
    if not user_id:
        _log(logging.WARNING, "invalid_input", reason="missing_user_id")
        return {"ok": False, "error": "invalid_input", "reply": _ASK_FOR_TEXT}
    if not isinstance(text, str) or not text.strip():
        _log(logging.WARNING, "invalid_input", reason="missing_text",
             user=_mask_phone(user_id))
        return {"ok": False, "error": "invalid_input", "reply": _ASK_FOR_TEXT}

    text = text.strip()
    consent_pending = bool(event.get("consent_pending"))
    rate_limited = bool(event.get("rate_limited"))

    _log(logging.INFO, "agent_start", user=_mask_phone(user_id),
         user_hash=_hash_id(user_id),
         message_id=event.get("message_id"),
         text_len=len(text), consent_pending=consent_pending,
         rate_limited=rate_limited,
         memory=bool(AGENTCORE_MEMORY_ID))

    try:
        # Build the Bedrock model targeting the inference profile with the
        # guardrail applied declaratively (RNF-13/14): BedrockModel forwards
        # guardrail_id/guardrail_version into every Converse request, so the
        # guardrail fires on model I/O with no manual ApplyGuardrail needed.
        model = BedrockModel(
            model_id=INFERENCE_PROFILE_ID,
            region_name=AWS_REGION,
            guardrail_id=GUARDRAIL_ID,
            guardrail_version=GUARDRAIL_VERSION,
        )

        # Shape the turn with the ingest-provided flags; ingest already enforced
        # consent/rate limits, the agent only reflects them in the conversation.
        prompt = text
        if consent_pending:
            prompt = (
                "[El usuario aun no ha dado su consentimiento: pide opt-in antes "
                "de ejecutar acciones.]\n" + prompt
            )

        agent = Agent(
            model=model,
            tools=_TOOLS,
            system_prompt=_SYSTEM_PROMPT,
            callback_handler=None,
        )

        result = agent(prompt)
        reply = _extract_reply(result)

        if not reply:
            # Never return {"ok": true, "reply": ""}; an empty turn is internal.
            _log(logging.ERROR, "agent_error", reason="empty_reply",
                 user_hash=_hash_id(user_id))
            return {"ok": False, "error": "internal"}

        _log(logging.INFO, "agent_done", user_hash=_hash_id(user_id),
             reply_len=len(reply))
        _record_simulated_reply(user_id, reply, event.get("message_id"))
        return {"ok": True, "reply": reply}

    except ModelThrottledException:
        _log(logging.WARNING, "agent_error", reason="bedrock_throttled",
             user_hash=_hash_id(user_id))
        return {"ok": False, "error": "bedrock_throttled"}
    except ReadTimeoutError:
        # Bedrock read-timeout maps to bedrock_throttled (retriable), NOT a
        # literal "timeout" — the closed error set has no "timeout" value.
        _log(logging.WARNING, "agent_error", reason="bedrock_read_timeout",
             user_hash=_hash_id(user_id))
        return {"ok": False, "error": "bedrock_throttled"}
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("ThrottlingException", "TooManyRequestsException",
                    "throttlingException"):
            _log(logging.WARNING, "agent_error", reason="bedrock_throttled",
                 user_hash=_hash_id(user_id))
            return {"ok": False, "error": "bedrock_throttled"}
        logger.exception(json.dumps({"event": "agent_error",
                                     "reason": "client_error",
                                     "user_hash": _hash_id(user_id)}))
        return {"ok": False, "error": "internal"}
    except Exception:  # noqa: BLE001 - never raise out of lambda_handler
        logger.exception(json.dumps({"event": "agent_error",
                                     "reason": "unexpected",
                                     "user_hash": _hash_id(user_id)}))
        return {"ok": False, "error": "internal"}
