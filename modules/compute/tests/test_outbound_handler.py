"""Outbound Lambda: the only socialmessaging SendWhatsAppMessage caller (RB-01).

The handler builds the WhatsApp Cloud API text object, encodes it as raw UTF-8
JSON bytes (NOT base64 -- VP-1), normalizes the origination phone-number ARN to
the bare id (VP-3), and returns the closed error set {invalid_input, send_failed}
without ever raising.

Run: python3 -m unittest discover -s modules/compute/tests
"""

import importlib.util
import json
import os
import unittest
from unittest import mock

os.environ.update({
    "META_API_VERSION": "v20.0",
    "LOG_LEVEL": "INFO",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
})

# Load the outbound handler under a unique module name so it never collides
# with the ingest test's `import handler` (both src dirs expose a `handler`
# module; discover shares one sys.modules, so a plain import would return
# whichever loaded first).
_HANDLER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "outbound", "handler.py"
)
_spec = importlib.util.spec_from_file_location("outbound_handler", _HANDLER_PATH)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)

from botocore.exceptions import ClientError  # noqa: E402

RECIPIENT = "5215512345678"  # 521 + 10 digits — the Mexican wa_id, sent verbatim
TEXT_HOLA = "hola, listo"
AWS_PHONE_ID = "976c72a700aac43eaf573ae050example"
PHONE_ARN = (
    "arn:aws:social-messaging:us-east-1:000000000000:phone-number-id/" + AWS_PHONE_ID
)
MESSAGE_ID = "wamid.OUT1"


class OutboundHandlerTests(unittest.TestCase):
    def setUp(self):
        handler._social = mock.MagicMock()
        handler._social.send_whatsapp_message.return_value = {"messageId": MESSAGE_ID}

    def test_valid_event_sends_and_returns_ok(self):
        event = {
            "to": RECIPIENT,
            "text": TEXT_HOLA,
            "origination_phone_number_id": PHONE_ARN,
        }
        result = handler.lambda_handler(event, None)

        self.assertEqual(result, {"ok": True, "message_id": MESSAGE_ID})
        handler._social.send_whatsapp_message.assert_called_once()
        kwargs = handler._social.send_whatsapp_message.call_args.kwargs
        # The full ARN is passed through unchanged (matches the AWS pattern
        # form `arn:...:phone-number-id/<id>`); extracting the bare hash would
        # drop the required `phone-number-id-` prefix and fail validation.
        self.assertEqual(kwargs["originationPhoneNumberId"], PHONE_ARN)
        self.assertEqual(kwargs["metaApiVersion"], "v20.0")
        expected_obj = {
            "messaging_product": "whatsapp",
            # The recipient wa_id gets a leading "+" (E.164); no 521->52 rewrite.
            "to": "+" + RECIPIENT,
            "type": "text",
            "text": {"body": TEXT_HOLA},
        }
        # message is the JSON STRING (not pre-encoded bytes) — matches the
        # AWS-documented working example; botocore handles the blob encoding.
        self.assertEqual(kwargs["message"], json.dumps(expected_obj))

    def test_phone_number_id_passthrough(self):
        # The full ARN (form `arn:...:phone-number-id/<id>`) and a bare
        # `phone-number-id-...` id are both valid originationPhoneNumberId
        # shapes, so both are passed through unchanged. Splitting the ARN to
        # the trailing hash (the old behavior) dropped the `phone-number-id-`
        # prefix and caused a ValidationException.
        self.assertEqual(handler._phone_number_id(PHONE_ARN), PHONE_ARN)
        bare = "phone-number-id-" + AWS_PHONE_ID
        self.assertEqual(handler._phone_number_id(bare), bare)
        self.assertIsNone(handler._phone_number_id(""))
        self.assertIsNone(handler._phone_number_id(None))

    def test_recipient_gets_plus_no_521_rewrite(self):
        # The 521... wa_id keeps its 521 (no 52 rewrite) and gains a leading
        # "+". The number-format probe confirmed "+521..." delivers while
        # "521..." (no "+") is rejected by EUM.
        event = {
            "to": RECIPIENT,
            "text": TEXT_HOLA,
            "origination_phone_number_id": PHONE_ARN,
        }
        handler.lambda_handler(event, None)
        kwargs = handler._social.send_whatsapp_message.call_args.kwargs
        sent = json.loads(kwargs["message"])
        self.assertEqual(sent["to"], "+" + RECIPIENT)

    def test_to_e164(self):
        # Prepends "+" when missing; leaves an already-"+" number alone.
        self.assertEqual(handler._to_e164("5215512345678"), "+5215512345678")
        self.assertEqual(handler._to_e164("+5215512345678"), "+5215512345678")
        self.assertEqual(handler._to_e164("  5215512345678  "), "+5215512345678")

    def test_missing_to_is_invalid_input(self):
        event = {"text": TEXT_HOLA, "origination_phone_number_id": PHONE_ARN}
        result = handler.lambda_handler(event, None)
        self.assertEqual(result, {"ok": False, "error": "invalid_input"})
        handler._social.send_whatsapp_message.assert_not_called()

    def test_empty_text_is_invalid_input(self):
        event = {
            "to": RECIPIENT,
            "text": "   ",
            "origination_phone_number_id": PHONE_ARN,
        }
        result = handler.lambda_handler(event, None)
        self.assertEqual(result, {"ok": False, "error": "invalid_input"})
        handler._social.send_whatsapp_message.assert_not_called()

    def test_missing_origination_is_invalid_input(self):
        event = {"to": RECIPIENT, "text": TEXT_HOLA}
        result = handler.lambda_handler(event, None)
        self.assertEqual(result, {"ok": False, "error": "invalid_input"})
        handler._social.send_whatsapp_message.assert_not_called()

    def test_client_error_is_send_failed(self):
        handler._social.send_whatsapp_message.side_effect = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "bad"}},
            "SendWhatsAppMessage",
        )
        event = {
            "to": RECIPIENT,
            "text": TEXT_HOLA,
            "origination_phone_number_id": PHONE_ARN,
        }
        result = handler.lambda_handler(event, None)
        self.assertEqual(result, {"ok": False, "error": "send_failed"})

    def test_sent_log_masks_recipient_and_omits_body(self):
        event = {
            "to": RECIPIENT,
            "text": TEXT_HOLA,
            "origination_phone_number_id": PHONE_ARN,
        }
        with self.assertLogs(handler.logger, level="INFO") as cm:
            handler.lambda_handler(event, None)
        joined = " ".join(cm.output)
        self.assertIn("sent", joined)
        self.assertIn("****5678", joined)
        self.assertNotIn(RECIPIENT, joined)
        self.assertNotIn(TEXT_HOLA, joined)
        self.assertIn("text_len", joined)


if __name__ == "__main__":
    unittest.main()
