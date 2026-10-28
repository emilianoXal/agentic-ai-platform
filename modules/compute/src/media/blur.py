from math import ceil, floor

from PIL import ImageFilter


def _pixel_box(box, width, height):
    left = max(0, min(width, floor(float(box.get("Left", 0)) * width)))
    top = max(0, min(height, floor(float(box.get("Top", 0)) * height)))
    right = max(left, min(width, ceil((float(box.get("Left", 0)) + float(box.get("Width", 0))) * width)))
    bottom = max(top, min(height, ceil((float(box.get("Top", 0)) + float(box.get("Height", 0))) * height)))
    return left, top, right, bottom


def blur_regions(image, boxes, radius=12):
    result = image.copy()
    for box in boxes:
        pixels = _pixel_box(box, *result.size)
        if pixels[0] == pixels[2] or pixels[1] == pixels[3]:
            continue
        region = result.crop(pixels)
        result.paste(region.filter(ImageFilter.GaussianBlur(radius=radius)), pixels)
    return result
