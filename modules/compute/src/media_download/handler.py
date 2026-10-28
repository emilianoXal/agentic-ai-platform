import json
import logging
import os

import boto3


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
_social = boto3.client("socialmessaging")


def _phone_number_id(value):
    """Return an originationPhoneNumberId accepted by GetWhatsAppMessageMedia.

    The API requires one of two shapes (same pattern as SendWhatsAppMessage:
    `(^phone-number-id-.*$)|(^arn:.*:phone-number-id/[0-9a-zA-Z]+$)`):
      1. a bare id that STARTS WITH `phone-number-id-`, or
      2. the FULL ARN `arn:...:phone-number-id/<id>`.

    ingest starts the sanitizer with context.MetaPhoneNumberIds[].arn. Passing
    that ARN through UNCHANGED matches form 2. Splitting on "/" yields only
    the trailing hash WITHOUT the required `phone-number-id-` prefix, which
    fails with ValidationException. A value that already starts with
    `phone-number-id-` (form 1) is also passed through.
    """
    if not value:
        return None
    return str(value)


def lambda_handler(event, context):
    response = _social.get_whatsapp_message_media(
        mediaId=event["mediaId"],
        originationPhoneNumberId=_phone_number_id(event["originationPhoneNumberId"]),
        metadataOnly=False,
        destinationS3File={"bucketName": event["bucket"], "key": "raw/"},
    )
    mime_type = response.get("mimeType") or "image/jpeg"
    extension = mime_type.split(";", 1)[0].strip().rsplit("/", 1)[-1]
    result = {
        "bucket": event["bucket"],
        "rawKey": "raw/" + event["mediaId"] + "." + extension,
        "sanitizedKey": event["sanitizedKey"],
        "mimeType": mime_type,
    }
    logger.info(json.dumps({"event": "media_downloaded"}))
    return result
