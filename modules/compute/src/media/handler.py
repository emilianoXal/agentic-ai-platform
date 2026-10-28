import io
import json
import logging
import os
import re

import boto3
from PIL import Image

from blur import blur_regions


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
FACE_MIN_CONFIDENCE = float(os.environ.get("FACE_MIN_CONFIDENCE", "80"))
TEXT_MIN_CONFIDENCE = float(os.environ.get("TEXT_MIN_CONFIDENCE", "80"))

logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
_s3 = boto3.client("s3")
_PLATE = re.compile(r"^[A-Z0-9]{5,10}$")


def _is_plate(text):
    compact = re.sub(r"[^A-Z0-9]", "", str(text).upper())
    return bool(
        _PLATE.fullmatch(compact)
        and any(char.isalpha() for char in compact)
        and any(char.isdigit() for char in compact)
    )


def detection_boxes(faces, texts):
    boxes = [
        detail["BoundingBox"]
        for detail in faces.get("FaceDetails", [])
        if detail.get("Confidence", 0) >= FACE_MIN_CONFIDENCE and detail.get("BoundingBox")
    ]
    boxes.extend(
        detection["Geometry"]["BoundingBox"]
        for detection in texts.get("TextDetections", [])
        if detection.get("Type") == "LINE"
        and detection.get("Confidence", 0) >= TEXT_MIN_CONFIDENCE
        and _is_plate(detection.get("DetectedText", ""))
        and detection.get("Geometry", {}).get("BoundingBox")
    )
    return boxes


def lambda_handler(event, context):
    bucket = event["bucket"]
    raw_key = event["rawKey"]
    sanitized_key = event["sanitizedKey"]
    boxes = detection_boxes(event.get("faces", {}), event.get("texts", {}))

    if not boxes:
        _s3.copy_object(
            Bucket=bucket,
            Key=sanitized_key,
            CopySource={"Bucket": bucket, "Key": raw_key},
            MetadataDirective="COPY",
        )
    else:
        source = _s3.get_object(Bucket=bucket, Key=raw_key)["Body"].read()
        with Image.open(io.BytesIO(source)) as image:
            output = io.BytesIO()
            image_format = image.format or "JPEG"
            blurred = blur_regions(image.convert("RGB"), boxes)
            blurred.save(output, format=image_format)
        _s3.put_object(
            Bucket=bucket,
            Key=sanitized_key,
            Body=output.getvalue(),
            ContentType=event.get("mimeType") or "image/jpeg",
        )

    logger.info(json.dumps({"event": "media_sanitized", "regions": len(boxes)}))
    return {"bucket": bucket, "sanitizedKey": sanitized_key, "regions": len(boxes)}
