import importlib.util
import io
import json
import os
import statistics
import sys
from copy import deepcopy

from PIL import Image


os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MEDIA_SRC = os.path.join(ROOT, "src", "media")
sys.path.insert(0, MEDIA_SRC)

from blur import blur_regions


spec = importlib.util.spec_from_file_location("media_handler", os.path.join(MEDIA_SRC, "handler.py"))
media_handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media_handler)

download_spec = importlib.util.spec_from_file_location(
    "media_download_handler", os.path.join(ROOT, "src", "media_download", "handler.py")
)
media_download_handler = importlib.util.module_from_spec(download_spec)
download_spec.loader.exec_module(media_download_handler)

create_report_spec = importlib.util.spec_from_file_location(
    "create_report_handler", os.path.join(ROOT, "..", "agent", "src", "create_report", "handler.py")
)
create_report_handler = importlib.util.module_from_spec(create_report_spec)
create_report_spec.loader.exec_module(create_report_handler)


def _synthetic_image():
    image = Image.new("RGB", (40, 30))
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), ((x * 37) % 256, (y * 53) % 256, ((x + y) * 29) % 256))
    return image


def _png_bytes(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeS3:
    def __init__(self, source):
        self.objects = {("media", "raw/image"): source}

    def copy_object(self, Bucket, Key, CopySource, MetadataDirective):
        source = (CopySource["Bucket"], CopySource["Key"])
        self.objects[(Bucket, Key)] = self.objects[source]

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = Body


def test_blur_changes_only_pixels_inside_face_and_plate_boxes():
    original = _synthetic_image()
    boxes = [
        {"Left": 0.1, "Top": 0.1, "Width": 0.25, "Height": 0.3},
        {"Left": 0.6, "Top": 0.5, "Width": 0.3, "Height": 0.3},
    ]
    blurred = blur_regions(original, boxes, radius=5)
    changed_inside = 0
    for y in range(original.height):
        for x in range(original.width):
            inside = (4 <= x < 14 and 3 <= y < 12) or (24 <= x < 36 and 15 <= y < 24)
            if inside:
                changed_inside += original.getpixel((x, y)) != blurred.getpixel((x, y))
            else:
                assert original.getpixel((x, y)) == blurred.getpixel((x, y))
    assert changed_inside > 0


def test_large_region_loses_feature_sized_detail_and_outside_is_unchanged():
    original = Image.new("L", (800, 800))
    original.putdata([255 if (x // 40) % 2 else 0 for y in range(800) for x in range(800)])
    box = {"Left": 0.1, "Top": 0.05, "Width": 0.75, "Height": 0.875}
    blurred = blur_regions(original, [box])
    inside = (80, 40, 680, 740)
    core = (inside[0] + 150, inside[1] + 150, inside[2] - 150, inside[3] - 150)
    before = statistics.pstdev(original.crop(core).getdata())
    after = statistics.pstdev(blurred.crop(core).getdata())
    assert after < before * 0.1
    for region in ((0, 0, 800, inside[1]), (0, inside[3], 800, 800), (0, 0, inside[0], 800), (inside[2], 0, 800, 800)):
        assert list(original.crop(region).getdata()) == list(blurred.crop(region).getdata())


def test_wide_plate_region_loses_character_sized_detail_and_outside_is_unchanged():
    original = Image.new("L", (1000, 400))
    original.putdata([255 if (x // 40) % 2 else 0 for y in range(400) for x in range(1000)])
    box = {"Left": 0.1, "Top": 0.25, "Width": 0.8, "Height": 0.5}
    blurred = blur_regions(original, [box])
    inside = (100, 100, 900, 300)
    core = (inside[0] + 150, inside[1] + 50, inside[2] - 150, inside[3] - 50)
    before = statistics.pstdev(original.crop(core).getdata())
    after = statistics.pstdev(blurred.crop(core).getdata())
    assert after < before * 0.2
    for region in ((0, 0, 1000, inside[1]), (0, inside[3], 1000, 400), (0, 0, inside[0], 400), (inside[2], 0, 1000, 400)):
        assert list(original.crop(region).getdata()) == list(blurred.crop(region).getdata())


def test_image_without_detections_is_copied_byte_for_byte():
    source = _png_bytes(_synthetic_image())
    fake_s3 = FakeS3(source)
    media_handler._s3 = fake_s3
    result = media_handler.lambda_handler(
        {
            "bucket": "media",
            "rawKey": "raw/image",
            "sanitizedKey": "sanitized/image",
            "faces": {"FaceDetails": []},
            "texts": {"TextDetections": []},
            "mimeType": "image/png",
        },
        None,
    )
    assert result["regions"] == 0
    assert fake_s3.objects[("media", "sanitized/image")] == source


def test_face_and_license_plate_detections_are_both_sanitized():
    boxes = media_handler.detection_boxes(
        {"FaceDetails": [{"Confidence": 99, "BoundingBox": {"Left": 0.1, "Top": 0.1, "Width": 0.2, "Height": 0.2}}]},
        {
            "TextDetections": [
                {
                    "Type": "LINE",
                    "Confidence": 98,
                    "DetectedText": "ABC-123-D",
                    "Geometry": {"BoundingBox": {"Left": 0.5, "Top": 0.6, "Width": 0.3, "Height": 0.1}},
                },
                {
                    "Type": "LINE",
                    "Confidence": 99,
                    "DetectedText": "QUERETARO",
                    "Geometry": {"BoundingBox": {"Left": 0, "Top": 0, "Width": 1, "Height": 0.1}},
                },
            ]
        },
    )
    assert len(boxes) == 2


class FakeSocial:
    def __init__(self, mime_type):
        self.mime_type = mime_type
        self.calls = []

    def get_whatsapp_message_media(self, **kwargs):
        self.calls.append(kwargs)
        return {"mimeType": self.mime_type}


def test_download_returns_key_where_whatsapp_writes_the_object():
    for mime_type, raw_key in (("image/jpeg", "raw/123.jpeg"), ("image/png", "raw/123.png")):
        fake_social = FakeSocial(mime_type)
        media_download_handler._social = fake_social
        result = media_download_handler.lambda_handler(
            {
                "bucket": "media",
                "mediaId": "123",
                "originationPhoneNumberId": "arn:aws:social-messaging:us-east-1:0:phone-number-id/abc",
                "sanitizedKey": "sanitized/report",
            },
            None,
        )
        assert fake_social.calls[0]["destinationS3File"] == {"bucketName": "media", "key": "raw/"}
        assert fake_social.calls[0]["originationPhoneNumberId"] == (
            "arn:aws:social-messaging:us-east-1:0:phone-number-id/abc"
        )
        assert result == {
            "bucket": "media",
            "rawKey": raw_key,
            "sanitizedKey": "sanitized/report",
            "mimeType": mime_type,
        }


def test_download_passes_full_origination_arn_to_whatsapp():
    fake_social = FakeSocial("image/jpeg")
    media_download_handler._social = fake_social
    arn = "arn:aws:social-messaging:us-east-1:636487155766:phone-number-id/e644d37f4dab45d5a57a5676effc9956"
    media_download_handler.lambda_handler(
        {
            "bucket": "media",
            "mediaId": "530339869524171",
            "originationPhoneNumberId": arn,
            "sanitizedKey": "sanitized/report",
        },
        None,
    )
    assert fake_social.calls[0]["originationPhoneNumberId"] == arn
    assert fake_social.calls[0]["originationPhoneNumberId"] != "e644d37f4dab45d5a57a5676effc9956"
    bare = "phone-number-id-e644d37f4dab45d5a57a5676effc9956"
    media_download_handler.lambda_handler(
        {
            "bucket": "media",
            "mediaId": "530339869524171",
            "originationPhoneNumberId": bare,
            "sanitizedKey": "sanitized/report",
        },
        None,
    )
    assert fake_social.calls[1]["originationPhoneNumberId"] == bare


def test_report_rejects_raw_media_references():
    assert create_report_handler._sanitized_media(
        ["raw/secret", "sanitized/photo", "https://example.invalid/raw", {"id": "123"}]
    ) == ["sanitized/photo"]


def _path(data, expression):
    value = data
    for part in expression.removeprefix("$.").split("."):
        value = value[part]
    return value


def _parameters(value, data):
    if isinstance(value, dict):
        result = {}
        for key, nested in value.items():
            if key.endswith(".$"):
                result[key[:-2]] = deepcopy(data) if nested == "$" else _path(data, nested)
            else:
                result[key] = _parameters(nested, data)
        return result
    return value


def _run_workflow(definition, initial, services):
    state_name = definition["StartAt"]
    data = deepcopy(initial)
    while True:
        state = definition["States"][state_name]
        result = services[state["Resource"]](_parameters(state.get("Parameters", {}), data))
        if state.get("OutputPath") == "$.Payload":
            data = result["Payload"]
        elif state.get("ResultPath"):
            data[state["ResultPath"].removeprefix("$.")] = result
        if state.get("End"):
            return data
        state_name = state["Next"]


def test_state_machine_runs_mocked_rekognition_before_sanitizing():
    template = open(os.path.join(ROOT, "media_state_machine.asl.json.tftpl"), encoding="utf-8").read()
    definition = json.loads(
        template.replace("${download_lambda_arn}", "download-function").replace(
            "${sanitize_lambda_arn}", "sanitize-function"
        )
    )
    calls = []

    rekognition_keys = []

    def detect(result):
        def call(params):
            rekognition_keys.append(params["Image"]["S3Object"]["Name"])
            return result
        return call

    def invoke(params):
        calls.append(params["FunctionName"])
        if params["FunctionName"] == "download-function":
            return {"Payload": {**params["Payload"], "rawKey": "raw/123.jpeg", "mimeType": "image/jpeg"}}
        assert params["Payload"]["faces"]["FaceDetails"]
        assert params["Payload"]["texts"]["TextDetections"]
        return {"Payload": {"sanitizedKey": params["Payload"]["sanitizedKey"], "regions": 2}}

    services = {
        "arn:aws:states:::lambda:invoke": invoke,
        "arn:aws:states:::aws-sdk:rekognition:detectFaces": detect(
            {"FaceDetails": [{"BoundingBox": {"Left": 0, "Top": 0, "Width": 0.2, "Height": 0.2}}]}
        ),
        "arn:aws:states:::aws-sdk:rekognition:detectText": detect(
            {"TextDetections": [{"DetectedText": "ABC123", "Type": "LINE"}]}
        ),
    }
    result = _run_workflow(
        definition,
        {
            "bucket": "media",
            "mediaId": "123",
            "originationPhoneNumberId": "phone-number-id/abc",
            "sanitizedKey": "sanitized/report",
        },
        services,
    )
    assert result == {"sanitizedKey": "sanitized/report", "regions": 2}
    assert calls == ["download-function", "sanitize-function"]
    assert rekognition_keys == ["raw/123.jpeg", "raw/123.jpeg"]
