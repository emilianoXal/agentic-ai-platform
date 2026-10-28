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
    result = {
        "bucket": event["bucket"],
        "rawKey": event["rawKey"],
        "sanitizedKey": event["sanitizedKey"],
        "mimeType": response.get("mimeType", "image/jpeg"),
    }
    logger.info(json.dumps({"event": "media_downloaded"}))
    return result
