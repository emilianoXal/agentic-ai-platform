import json
import logging
import os

import boto3


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
_social = boto3.client("socialmessaging")


def _phone_number_id(value):
    return str(value).rsplit("/", 1)[-1]


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
